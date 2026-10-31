import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from geopy.distance import geodesic

from config import Config
from models.db_models import db, Report, Admin, ActivityLog
from models.ai_classifier import classifier
from utils.image_processor import save_uploaded_image
from utils.priority_engine import compute_priority
from utils.auto_router import route_to_department, generate_tracking_id
from utils.notification import notify_department, notify_citizen

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

DUPLICATE_RADIUS_METERS = 50


def init_db():
    with app.app_context():
        db.create_all()
        if not Admin.query.filter_by(username='admin').first():
            admin = Admin(
                username='admin',
                password_hash=generate_password_hash('admin123'),
                department='General Municipal Office'
            )
            db.session.add(admin)
            db.session.commit()


def check_duplicate(category, lat, lon):
    """Check if a similar unresolved report exists nearby."""
    if lat is None or lon is None:
        return None
    candidates = Report.query.filter(
        Report.category == category,
        Report.status.in_(['Pending', 'In Progress'])
    ).all()
    for c in candidates:
        if c.latitude and c.longitude:
            dist = geodesic((lat, lon), (c.latitude, c.longitude)).meters
            if dist <= DUPLICATE_RADIUS_METERS:
                return c
    return None


# ---------------------- Public Routes ----------------------

@app.route('/')
def index():
    total_reports = Report.query.count()
    resolved = Report.query.filter_by(status='Resolved').count()
    pending = Report.query.filter_by(status='Pending').count()
    in_progress = Report.query.filter_by(status='In Progress').count()
    recent = Report.query.order_by(Report.created_at.desc()).limit(6).all()
    return render_template('index.html', total=total_reports, resolved=resolved,
                           pending=pending, in_progress=in_progress, recent=recent)


@app.route('/report', methods=['GET', 'POST'])
def report_issue():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        description = request.form.get('description', '')
        address = request.form.get('address')
        lat = request.form.get('latitude')
        lon = request.form.get('longitude')
        manual_category = request.form.get('category')  # optional override

        lat = float(lat) if lat else None
        lon = float(lon) if lon else None

        image_file = request.files.get('image')
        image_rel_path = save_uploaded_image(image_file) if image_file else None

        if not image_rel_path:
            flash('A valid image is required for AI analysis.', 'danger')
            return redirect(url_for('report_issue'))

        full_image_path = os.path.join(Config.UPLOAD_FOLDER, os.path.basename(image_rel_path))

        # --- AI CLASSIFICATION ---
        ai_category, confidence = classifier.predict(full_image_path)
        category = manual_category if manual_category else ai_category

        # --- SEVERITY ANALYSIS ---
        severity_score = classifier.analyze_severity(full_image_path)

        # --- DUPLICATE CHECK ---
        duplicate = check_duplicate(category, lat, lon)

        # --- PRIORITY SCORING ---
        priority_score, priority_level = compute_priority(category, severity_score, 0, description)

        # --- AUTO ROUTING ---
        department = route_to_department(category)
        tracking_id = generate_tracking_id()

        new_report = Report(
            tracking_id=tracking_id,
            reporter_name=name,
            reporter_email=email,
            reporter_phone=phone,
            category=category,
            description=description,
            image_path=image_rel_path,
            location_address=address,
            latitude=lat,
            longitude=lon,
            ai_confidence=confidence,
            severity_score=severity_score,
            priority_level=priority_level,
            assigned_department=department,
            duplicate_of=duplicate.id if duplicate else None,
            status='Pending'
        )
        db.session.add(new_report)
        db.session.commit()

        log = ActivityLog(report_id=new_report.id, action='Report created via AI classification',
                           performed_by=name)
        db.session.add(log)
        db.session.commit()

        # Simulate notifications
        notify_department(department, tracking_id, category, priority_level)
        notify_citizen(email, tracking_id, 'Pending')

        if duplicate:
            duplicate.upvotes += 1
            db.session.commit()
            flash(f'Similar report already exists (#{duplicate.tracking_id}). '
                  f'Your report has been linked and upvoted the existing issue!', 'info')
        else:
            flash(f'Report submitted successfully! Your tracking ID is {tracking_id}', 'success')

        return redirect(url_for('track_issue', tracking_id=tracking_id))

    return render_template('report.html', categories=list(Config.DEPARTMENTS.keys()))


@app.route('/track/<tracking_id>')
def track_issue(tracking_id):
    report = Report.query.filter_by(tracking_id=tracking_id).first_or_404()
    logs = ActivityLog.query.filter_by(report_id=report.id).order_by(ActivityLog.timestamp).all()
    return render_template('track_issue.html', report=report, logs=logs)


@app.route('/dashboard')
def dashboard():
    category_filter = request.args.get('category', 'all')
    status_filter = request.args.get('status', 'all')
    priority_filter = request.args.get('priority', 'all')

    query = Report.query
    if category_filter != 'all':
        query = query.filter_by(category=category_filter)
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)
    if priority_filter != 'all':
        query = query.filter_by(priority_level=priority_filter)

    reports = query.order_by(Report.severity_score.desc()).all()
    return render_template('dashboard.html', reports=reports,
                           categories=list(Config.DEPARTMENTS.keys()))


@app.route('/upvote/<int:report_id>', methods=['POST'])
def upvote(report_id):
    report = Report.query.get_or_404(report_id)
    report.upvotes += 1
    # Recompute priority after upvote
    new_score, new_level = compute_priority(report.category, report.severity_score,
                                             report.upvotes, report.description)
    report.priority_level = new_level
    db.session.commit()
    return jsonify({'success': True, 'upvotes': report.upvotes, 'priority': new_level})


# ---------------------- Admin Routes ----------------------

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        admin = Admin.query.filter_by(username=username).first()
        if admin and check_password_hash(admin.password_hash, password):
            session['admin_id'] = admin.id
            session['admin_name'] = admin.username
            return redirect(url_for('admin_dashboard'))
        flash('Invalid credentials', 'danger')
    return render_template('admin_login.html')


@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))


@app.route('/admin/dashboard')
def admin_dashboard():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))

    status_filter = request.args.get('status', 'all')
    query = Report.query
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    reports = query.order_by(Report.severity_score.desc()).all()

    stats = {
        'total': Report.query.count(),
        'pending': Report.query.filter_by(status='Pending').count(),
        'in_progress': Report.query.filter_by(status='In Progress').count(),
        'resolved': Report.query.filter_by(status='Resolved').count(),
        'high_priority': Report.query.filter_by(priority_level='High').count(),
    }
    return render_template('admin_dashboard.html', reports=reports, stats=stats)


@app.route('/admin/update_status/<int:report_id>', methods=['POST'])
def update_status(report_id):
    if 'admin_id' not in session:
        return jsonify({'error': 'unauthorized'}), 401

    report = Report.query.get_or_404(report_id)
    new_status = request.form.get('status')
    report.status = new_status
    if new_status == 'Resolved':
        report.resolved_at = datetime.utcnow()

    db.session.commit()

    log = ActivityLog(report_id=report.id, action=f'Status changed to {new_status}',
                       performed_by=session.get('admin_name', 'Admin'))
    db.session.add(log)
    db.session.commit()

    notify_citizen(report.reporter_email, report.tracking_id, new_status)

    return jsonify({'success': True, 'status': new_status})


@app.route('/api/stats')
def api_stats():
    """API endpoint for charts on dashboard."""
    categories = {}
    for cat in Config.DEPARTMENTS.keys():
        categories[cat] = Report.query.filter_by(category=cat).count()

    priorities = {
        'High': Report.query.filter_by(priority_level='High').count(),
        'Medium': Report.query.filter_by(priority_level='Medium').count(),
        'Low': Report.query.filter_by(priority_level='Low').count(),
    }

    return jsonify({'categories': categories, 'priorities': priorities})


if __name__ == '__main__':
    init_db()
    app.run(debug=True)
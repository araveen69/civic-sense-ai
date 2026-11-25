import os
import re
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from geopy.distance import geodesic
from geopy.geocoders import Nominatim

from config import Config
from models.db_models import db, Report, Admin, ActivityLog, Feedback
from models.ai_classifier import classifier
from utils.image_processor import save_uploaded_image
from utils.priority_engine import compute_priority
from utils.auto_router import route_to_department, generate_tracking_id
from utils.notification import notify_department

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

DUPLICATE_RADIUS_METERS = 50
VALID_STATUSES = ('Pending', 'In Progress', 'Resolved', 'Rejected')

geocoder = Nominatim(user_agent='civic-sense-ai', timeout=8)
GEOCODE_CACHE = {}


def geocode_address(address, description=''):
    if not address and not description:
        return None, None
    cache_key = f"{address or ''}|{description or ''}".strip().lower()
    if cache_key in GEOCODE_CACHE:
        return GEOCODE_CACHE[cache_key]
    location_text = ' '.join(filter(None, [description.strip(), address.strip()]))
    candidates = [
        description.strip() if description else '',
        address.strip() if address else '',
        location_text,
    ]
    combined_text = f"{address or ''} {description or ''}".lower()
    if 'silk board' in combined_text:
        candidates.insert(0, 'Silk Board Junction, Bengaluru, Karnataka, India')
    parts = [part.strip() for part in (address or '').split(',') if part.strip()]
    candidates.extend([
        ', '.join(parts[-2:]) if len(parts) >= 2 else '',
        parts[-1] if parts else '',
    ])
    coordinates = (None, None)
    for candidate in dict.fromkeys(candidate for candidate in candidates if candidate):
        try:
            location = geocoder.geocode(candidate)
            if location:
                coordinates = (location.latitude, location.longitude)
                break
        except Exception:
            continue
    GEOCODE_CACHE[cache_key] = coordinates
    return coordinates


def normalize_status(status):
    if not status:
        return 'Pending'
    normalized = ' '.join(status.strip().replace('_', ' ').replace('-', ' ').split()).lower()
    return {
        'pending': 'Pending',
        'in progress': 'In Progress',
        'resolved': 'Resolved',
        'rejected': 'Rejected',
    }.get(normalized, 'Pending')


def init_db():
    with app.app_context():
        db.create_all()
        for report in Report.query.all():
            canonical_status = normalize_status(report.status)
            if report.status != canonical_status:
                report.status = canonical_status
            if (report.latitude is None or report.longitude is None or
                    'silk board' in (report.description or '').lower()):
                latitude, longitude = geocode_address(
                    report.location_address,
                    report.description
                )
                if latitude is not None and longitude is not None:
                    report.latitude = latitude
                    report.longitude = longitude
        db.session.commit()
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


def answer_civic_question(question):
    normalized = question.lower().replace('_', ' ')
    tracking_match = re.search(r'\bCIV-\d{6}-[A-Z0-9]{5}\b', question, re.IGNORECASE)

    if tracking_match:
        tracking_id = tracking_match.group(0).upper()
        report = Report.query.filter_by(tracking_id=tracking_id).first()
        if not report:
            return (f"I couldn't find a report with tracking ID {tracking_id}. "
                    "Please check the ID and try again.")
        return (
            f"Report {report.tracking_id} is currently {report.status}. "
            f"It is a {report.priority_level.lower()}-priority "
            f"{report.category.replace('_', ' ')} issue assigned to "
            f"{report.assigned_department or 'the relevant department'}. "
            f"Reported on {report.created_at.strftime('%Y-%m-%d')}. "
            f"You can view its activity timeline on the tracking page."
        )

    if any(term in normalized for term in ('track', 'tracking id', 'report status', 'status of my')):
        return ("To check a report, send its tracking ID (for example, "
                "CIV-240101-ABCDE) and I can look up its current status.")

    if any(term in normalized for term in ('how do i report', 'how to report', 'submit a report',
                                             'report an issue', 'file a complaint')):
        return ("Go to Report Issue, enter your contact details and the issue location, "
                "describe the problem, and upload a photo. Submit the form to receive a "
                "tracking ID. You can use that ID to check the report's status.")

    if any(term in normalized for term in ('what can i report', 'issue categories',
                                             'types of issue', 'types of report')):
        categories = ', '.join(category.replace('_', ' ') for category in Config.DEPARTMENTS)
        return f"You can report civic issues such as {categories}. Choose the closest category in the report form."

    if any(term in normalized for term in ('department', 'who handles', 'responsible for')):
        for category, department in Config.DEPARTMENTS.items():
            category_name = re.escape(category.replace('_', ' '))
            if re.search(rf'\b{category_name}s?\b', normalized):
                return (f"{department} handles {category.replace('_', ' ')} reports. "
                        "Reports are routed to the responsible department when submitted.")
        return ("Reports are automatically routed to the responsible department based on "
                "their category. Ask about a specific issue, such as potholes or streetlights.")

    if any(term in normalized for term in ('how many', 'statistics', 'stats', 'report count',
                                             'total reports')):
        total = Report.query.count()
        pending = Report.query.filter_by(status='Pending').count()
        in_progress = Report.query.filter_by(status='In Progress').count()
        resolved = Report.query.filter_by(status='Resolved').count()
        return (f"There are {total} reports in total: {pending} pending, "
                f"{in_progress} in progress, and {resolved} resolved.")

    if any(term in normalized for term in ('priority', 'high priority', 'severity')):
        return ("Priority is based on the issue category, AI-assessed severity, and community "
                "upvotes. High-priority reports are highlighted for attention; the public "
                "dashboard shows current report priorities.")

    if 'pending' in normalized or 'in progress' in normalized or 'resolved' in normalized:
        return ("Pending means a report has been submitted and is awaiting action. In Progress "
                "means the responsible department is working on it. Resolved means the issue "
                "has been marked as fixed.")

    return ("I can help with reporting a civic issue, supported issue categories, department "
            "routing, report priorities, live report counts, or checking a report's status. "
            "For a status lookup, include your tracking ID.")


# ---------------------- Public Routes ----------------------

@app.route('/')
def index():
    total_reports = Report.query.count()
    resolved = Report.query.filter_by(status='Resolved').count()
    pending = Report.query.filter_by(status='Pending').count()
    in_progress = Report.query.filter_by(status='In Progress').count()
    recent = Report.query.order_by(Report.created_at.desc()).limit(6).all()
    community_reports = Report.query.filter(
        Report.status.in_(['Pending', 'In Progress'])
    ).order_by(Report.upvotes.desc(), Report.created_at.desc()).limit(6).all()
    return render_template('index.html', total=total_reports, resolved=resolved,
                           pending=pending, in_progress=in_progress, recent=recent,
                           community_reports=community_reports)


@app.route('/feedback', methods=['GET', 'POST'])
def submit_feedback():
    categories = ('Suggestion', 'Bug report', 'General')
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '')
        message = request.form.get('message', '').strip()
        try:
            rating = int(request.form.get('rating', ''))
        except (TypeError, ValueError):
            rating = 0

        if category not in categories:
            flash('Please choose a valid feedback category.', 'danger')
        elif not 1 <= rating <= 5:
            flash('Please select a rating from 1 to 5.', 'danger')
        elif not message:
            flash('Please enter your feedback before submitting.', 'danger')
        elif len(message) > 2000:
            flash('Please keep your feedback under 2,000 characters.', 'danger')
        elif len(name) > 100:
            flash('Please keep your name under 100 characters.', 'danger')
        else:
            db.session.add(Feedback(
                name=name or None,
                category=category,
                rating=rating,
                message=message
            ))
            db.session.commit()
            flash('Thank you for sharing your feedback!', 'success')
            return redirect(url_for('submit_feedback'))

    return render_template('feedback.html', categories=categories)


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
        if (lat is None or lon is None) and address:
            lat, lon = geocode_address(address)

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

        # Notify the assigned department.
        notify_department(department, tracking_id, category, priority_level)

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
        query = query.filter_by(status=normalize_status(status_filter))
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
        query = query.filter_by(status=normalize_status(status_filter))

    reports = query.order_by(Report.severity_score.desc()).all()

    stats = {
        'total': Report.query.count(),
        'pending': Report.query.filter_by(status='Pending').count(),
        'in_progress': Report.query.filter_by(status='In Progress').count(),
        'resolved': Report.query.filter_by(status='Resolved').count(),
        'high_priority': Report.query.filter_by(priority_level='High').count(),
    }
    feedback_items = Feedback.query.order_by(Feedback.submitted_at.desc()).limit(5).all()
    return render_template('admin_dashboard.html', reports=reports, stats=stats,
                           feedback_items=feedback_items)


@app.route('/admin/feedback')
def admin_feedback():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))

    feedback_items = Feedback.query.order_by(Feedback.submitted_at.desc()).all()
    return render_template('admin_feedback.html', feedback_items=feedback_items)


@app.route('/admin/update_status/<int:report_id>', methods=['POST'])
def update_status(report_id):
    if 'admin_id' not in session:
        return jsonify({'error': 'unauthorized'}), 401

    report = Report.query.get_or_404(report_id)
    new_status = normalize_status(request.form.get('status'))
    report.status = new_status
    if new_status == 'Resolved':
        report.resolved_at = datetime.utcnow()
    else:
        report.resolved_at = None

    db.session.commit()

    log = ActivityLog(report_id=report.id, action=f'Status changed to {new_status}',
                       performed_by=session.get('admin_name', 'Admin'))
    db.session.add(log)
    db.session.commit()

    return jsonify({'success': True, 'status': new_status})


@app.route('/admin/delete_complaint/<int:report_id>', methods=['POST'])
def delete_complaint(report_id):
    if 'admin_id' not in session:
        return jsonify({'error': 'unauthorized'}), 401

    report = Report.query.get_or_404(report_id)
    tracking_id = report.tracking_id
    image_path = report.image_path

    # Preserve a deletion audit entry after removing report-specific logs.
    deletion_log = ActivityLog(
        report_id=None,
        action=f'Complaint #{tracking_id} deleted',
        performed_by=session.get('admin_name', 'Admin')
    )
    db.session.add(deletion_log)

    ActivityLog.query.filter_by(report_id=report.id).delete(synchronize_session=False)
    Report.query.filter_by(duplicate_of=report.id).update(
        {Report.duplicate_of: None},
        synchronize_session=False
    )
    db.session.delete(report)
    db.session.commit()

    if image_path:
        image_filename = os.path.basename(image_path)
        image_full_path = os.path.join(Config.UPLOAD_FOLDER, image_filename)
        if os.path.isfile(image_full_path):
            try:
                os.remove(image_full_path)
            except OSError:
                app.logger.warning('Unable to delete uploaded image: %s', image_full_path)

    return jsonify({'success': True, 'tracking_id': tracking_id})


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


@app.route('/api/assistant', methods=['POST'])
def api_assistant():
    if not request.is_json:
        return jsonify({'error': 'Send your question as JSON.'}), 415

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({'error': 'A JSON object with a question is required.'}), 400

    question = payload.get('question')
    if not isinstance(question, str) or not question.strip():
        return jsonify({'error': 'Please enter a question.'}), 400
    if len(question) > 500:
        return jsonify({'error': 'Please keep your question under 500 characters.'}), 400

    return jsonify({'answer': answer_civic_question(question.strip())})


@app.route('/api/reports/map')
def api_reports_map():
    """Return geolocated reports, optionally filtered with dashboard query parameters."""
    category_filter = request.args.get('category', 'all')
    status_filter = request.args.get('status', 'all')
    priority_filter = request.args.get('priority', 'all')

    query = Report.query
    if category_filter != 'all':
        query = query.filter_by(category=category_filter)
    if status_filter != 'all':
        query = query.filter_by(status=normalize_status(status_filter))
    if priority_filter != 'all':
        query = query.filter_by(priority_level=priority_filter)

    reports = []
    for report in query.order_by(Report.created_at.desc()).all():
        data = report.to_dict()
        latitude = report.latitude
        longitude = report.longitude
        if latitude is None or longitude is None:
            latitude, longitude = geocode_address(
                report.location_address,
                report.description
            )
        if latitude is not None and longitude is not None:
            data['latitude'] = latitude
            data['longitude'] = longitude
            reports.append(data)

    return jsonify({'reports': reports})


if __name__ == '__main__':
    init_db()
    app.run(debug=True)
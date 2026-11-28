import math
import os
import re
from datetime import datetime, timedelta
from flask import Flask, abort, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from geopy.distance import geodesic
from geopy.exc import GeocoderServiceError
from geopy.geocoders import Nominatim
from sqlalchemy import or_

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


def filtered_report_query(args):
    query = Report.query
    category = args.get('category', 'all')
    status = args.get('status', 'all')
    priority = args.get('priority', 'all')
    search = args.get('search', '').strip()
    start_date = args.get('start_date', '').strip()
    end_date = args.get('end_date', '').strip()

    if category != 'all':
        query = query.filter_by(category=category)
    if status != 'all':
        query = query.filter_by(status=normalize_status(status))
    if priority != 'all':
        query = query.filter_by(priority_level=priority)
    if len(search) > 100:
        abort(400, description='Search text must be 100 characters or fewer.')
    if search:
        search_pattern = f'%{search}%'
        query = query.filter(or_(
            Report.tracking_id.ilike(search_pattern),
            Report.category.ilike(search_pattern),
            Report.description.ilike(search_pattern),
            Report.location_address.ilike(search_pattern),
        ))

    try:
        start = datetime.strptime(start_date, '%Y-%m-%d') if start_date else None
        end = datetime.strptime(end_date, '%Y-%m-%d') if end_date else None
    except ValueError:
        abort(400, description='Dates must use the YYYY-MM-DD format.')

    if start and end and start > end:
        abort(400, description='Start date must be on or before end date.')
    if start:
        query = query.filter(Report.created_at >= start)
    if end:
        query = query.filter(Report.created_at < end + timedelta(days=1))

    return query


def answer_civic_question(question):
    normalized = question.lower().replace('_', ' ')
    tracking_match = re.search(r'\bCIV-\d{6}-[A-Z0-9]{5}\b', question, re.IGNORECASE)

    if tracking_match:
        tracking_id = tracking_match.group(0).upper()
        report = Report.query.filter_by(tracking_id=tracking_id).first()
        if not report:
            return (f"I couldn't find a report with tracking ID {tracking_id}. "
                    "Check the letters and numbers on your submission receipt, then try again. "
                    "Tracking IDs look like CIV-240101-ABCDE.")
        status_explanations = {
            'Pending': 'It has been received and is waiting for a department update.',
            'In Progress': ('The responsible department has marked work as underway; '
                            'this does not necessarily mean the issue is fixed.'),
            'Resolved': ('It has been marked as fixed. If the issue is still present, '
                         'submit a follow-up report and mention this tracking ID.'),
            'Rejected': ('It has been marked as rejected. Check the activity timeline for '
                         'any recorded context; a rejection reason may not be available.'),
        }
        status_explanation = status_explanations.get(
            report.status,
            'Check the tracking page for the latest recorded update.',
        )
        return (
            f"Report {report.tracking_id}\n"
            f"Current status: {report.status}. {status_explanation}\n"
            f"Issue: {report.category.replace('_', ' ')}\n"
            f"Priority: {report.priority_level}. This is an automated estimate to help "
            "organize attention, not a promised response time.\n"
            f"Assigned department: {report.assigned_department or 'Not assigned'}\n"
            f"Submitted: {report.created_at.strftime('%Y-%m-%d')}.\n"
            "Open the tracking page to review the recorded activity timeline."
        )

    if any(term in normalized for term in (
            'track', 'tracking id', 'report status', 'status of my',
            'what is the status', 'check the status', 'check my report')):
        return ("To check a report, send its tracking ID (for example, "
                "CIV-240101-ABCDE). I can look up the latest status, assigned department, "
                "priority estimate, submission date, and recorded activity. I cannot predict "
                "when the issue will be fixed.")

    if any(term in normalized for term in ('how do i report', 'how to report', 'submit a report',
                                             'report an issue', 'file a complaint')):
        return (
            "To report a civic issue:\n"
            "1. Open Report Issue and enter your name and email (required; phone is optional).\n"
            "2. Upload a photo; it is required for the image analysis. You may choose a "
            "category yourself or let the app suggest one from the image.\n"
            "3. Add a description and address if available. You can also try the location "
            "button, but location details are optional.\n"
            "4. Submit the form and save the tracking ID shown on the confirmation page.\n"
            "Use that ID in this assistant or on the tracking page to check recorded updates. "
            "The image-based category and priority are estimates, so check that the category "
            "fits your issue."
        )

    if any(term in normalized for term in ('what can i report', 'issue categories',
                                             'types of issue', 'types of report')):
        categories = ', '.join(
            category.replace('_', ' ') for category in Config.DEPARTMENTS
        )
        return (
            f"This app accepts reports for: {categories}. Choose the closest category in "
            "the report form. Category suggestions from the photo can be imperfect, and "
            "you can select a category yourself."
        )

    if any(term in normalized for term in ('department', 'who handles', 'responsible for')):
        for category, department in Config.DEPARTMENTS.items():
            category_name = re.escape(category.replace('_', ' '))
            if re.search(rf'\b{category_name}s?\b', normalized):
                return (
                    f"{department} is the department this app maps to "
                    f"{category.replace('_', ' ')} reports. When a report in that category "
                    "is submitted, the app assigns it there. The tracking page shows the "
                    "current assignment and recorded status updates."
                )
        return ("Reports are automatically routed to the responsible department based on "
                "their selected category when submitted. Ask about a supported category "
                "such as potholes, garbage, or streetlights to see its department.")

    if any(term in normalized for term in ('how many', 'statistics', 'stats', 'report count',
                                             'total reports')):
        total = Report.query.count()
        pending = Report.query.filter_by(status='Pending').count()
        in_progress = Report.query.filter_by(status='In Progress').count()
        resolved = Report.query.filter_by(status='Resolved').count()
        rejected = Report.query.filter_by(status='Rejected').count()
        return (
            f"The app currently stores {total} reports: {pending} pending "
            f"(awaiting an update), {in_progress} in progress, {resolved} resolved, "
            f"and {rejected} rejected. These are current database counts, not a forecast."
        )

    if any(term in normalized for term in ('priority', 'high priority', 'severity')):
        return ("Priority is based on the issue category, AI-assessed severity, and community "
                "upvotes, with a limited boost for urgency words in the description. The "
                "result is an automated estimate used to help order reports; it can be "
                "imperfect and does not guarantee how quickly a department will respond. "
                "The public dashboard shows each report's current priority.")

    status_explanations = {
        'pending': 'Pending means the report was received and is waiting for a department update.',
        'in progress': ('In Progress means the department has marked work as underway; '
                        'it does not necessarily mean the issue is fixed.'),
        'resolved': ('Resolved means the report has been marked as fixed. If the issue is '
                     'still present, submit a follow-up report and reference the original ID.'),
        'rejected': ('Rejected means the report was marked as rejected. Check its activity '
                     'timeline for any recorded context; a reason may not be available.'),
    }
    for status, explanation in status_explanations.items():
        if re.search(rf'\b{re.escape(status)}\b', normalized):
            return explanation

    return ("I can help with reporting a civic issue, supported issue categories, department "
            "routing, report priorities, live report counts, or checking a report's status. "
            "For a status lookup, include your tracking ID (for example, CIV-240101-ABCDE). "
            "I only use information available in this app, so I may not know details that "
            "have not been recorded.")


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
    sort = request.args.get('sort', 'priority')
    sort_options = {
        'priority': Report.severity_score.desc(),
        'recent': Report.created_at.desc(),
        'oldest': Report.created_at.asc(),
        'upvotes': Report.upvotes.desc(),
    }
    if sort not in sort_options:
        abort(400, description='Invalid report sort order.')

    pagination = filtered_report_query(request.args).order_by(
        sort_options[sort]
    ).paginate(page=request.args.get('page', 1, type=int), per_page=9, error_out=False)
    return render_template(
        'dashboard.html',
        pagination=pagination,
        categories=list(Config.DEPARTMENTS.keys()),
    )


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
                           feedback_items=feedback_items,
                           departments=sorted(set(Config.DEPARTMENTS.values())))


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


@app.route('/admin/assign_department/<int:report_id>', methods=['POST'])
def assign_department(report_id):
    if 'admin_id' not in session:
        return jsonify({'error': 'unauthorized'}), 401

    department = request.form.get('department')
    if department not in Config.DEPARTMENTS.values():
        return jsonify({'error': 'Invalid department.'}), 400

    report = Report.query.get_or_404(report_id)
    if report.assigned_department == department:
        return jsonify({'success': True, 'department': department})

    report.assigned_department = department
    db.session.add(ActivityLog(
        report_id=report.id,
        action=f'Department changed to {department}',
        performed_by=session.get('admin_name', 'Admin')
    ))
    db.session.commit()
    notify_department(department, report.tracking_id, report.category, report.priority_level)

    return jsonify({'success': True, 'department': department})


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
    query = filtered_report_query(request.args)
    categories = {}
    for cat in Config.DEPARTMENTS.keys():
        categories[cat] = query.filter_by(category=cat).count()

    priorities = {
        'High': query.filter_by(priority_level='High').count(),
        'Medium': query.filter_by(priority_level='Medium').count(),
        'Low': query.filter_by(priority_level='Low').count(),
    }
    trend_rows = query.with_entities(
        db.func.date(Report.created_at),
        db.func.count(Report.id),
    ).group_by(
        db.func.date(Report.created_at)
    ).order_by(
        db.func.date(Report.created_at)
    ).all()

    return jsonify({
        'categories': categories,
        'priorities': priorities,
        'trend': {
            'dates': [str(day) for day, _ in trend_rows],
            'counts': [count for _, count in trend_rows],
        },
    })


@app.route('/api/notifications')
def api_notifications():
    """Return recent complaint notifications without reporter contact details."""
    after_id = request.args.get('after_id')
    if after_id is None:
        reports = Report.query.order_by(Report.id.desc()).limit(5).all()
    else:
        try:
            after_id = int(after_id)
        except ValueError:
            abort(400, description='Notification cursor must be a non-negative integer.')
        if after_id < 0:
            abort(400, description='Notification cursor must be a non-negative integer.')
        reports = Report.query.filter(
            Report.id > after_id
        ).order_by(Report.id.asc()).limit(20).all()

    notifications = [{
        'id': report.id,
        'tracking_id': report.tracking_id,
        'category': report.category,
        'location': report.location_address or 'Location not specified',
        'created_at': report.created_at.strftime('%b %d, %Y %I:%M %p UTC'),
        'url': url_for('track_issue', tracking_id=report.tracking_id),
    } for report in reports]
    return jsonify({'notifications': notifications})


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


@app.route('/api/location/reverse', methods=['POST'])
def api_reverse_geocode():
    if not request.is_json:
        return jsonify({'error': 'Send coordinates as JSON.'}), 415

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({'error': 'A JSON object with coordinates is required.'}), 400

    try:
        latitude = float(payload['latitude'])
        longitude = float(payload['longitude'])
    except (KeyError, OverflowError, TypeError, ValueError):
        return jsonify({'error': 'Valid latitude and longitude are required.'}), 400

    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        return jsonify({'error': 'Latitude or longitude is out of range.'}), 400

    try:
        location = geocoder.reverse(
            (latitude, longitude),
            exactly_one=True,
            language='en'
        )
    except GeocoderServiceError:
        app.logger.warning('Reverse geocoding service is unavailable.')
        return jsonify({'error': 'Unable to look up the address right now.'}), 503

    if not location or not location.address:
        return jsonify({'error': 'No address was found for this location.'}), 404

    return jsonify({'address': location.address})


@app.route('/api/reports/map')
def api_reports_map():
    """Return geolocated reports, optionally filtered with dashboard query parameters."""
    reports = []
    for report in filtered_report_query(request.args).order_by(Report.created_at.desc()).all():
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
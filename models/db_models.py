from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Report(db.Model):
    __tablename__ = 'reports'

    id = db.Column(db.Integer, primary_key=True)
    tracking_id = db.Column(db.String(20), unique=True, nullable=False)

    # Reporter info
    reporter_name = db.Column(db.String(100), nullable=False)
    reporter_email = db.Column(db.String(120), nullable=False)
    reporter_phone = db.Column(db.String(20))

    # Issue details
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    image_path = db.Column(db.String(200))

    # Location
    location_address = db.Column(db.String(300))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)

    # AI-generated fields
    ai_confidence = db.Column(db.Float, default=0.0)
    severity_score = db.Column(db.Float, default=0.0)
    priority_level = db.Column(db.String(20), default='Low')
    assigned_department = db.Column(db.String(100))
    duplicate_of = db.Column(db.Integer, db.ForeignKey('reports.id'), nullable=True)

    # Status tracking
    status = db.Column(db.String(30), default='Pending')  # Pending, In Progress, Resolved, Rejected
    upvotes = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'tracking_id': self.tracking_id,
            'reporter_name': self.reporter_name,
            'category': self.category,
            'description': self.description,
            'image_path': self.image_path,
            'location_address': self.location_address,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'ai_confidence': self.ai_confidence,
            'severity_score': self.severity_score,
            'priority_level': self.priority_level,
            'assigned_department': self.assigned_department,
            'status': self.status,
            'upvotes': self.upvotes,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M'),
        }


class Admin(db.Model):
    __tablename__ = 'admins'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    department = db.Column(db.String(100))


class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'

    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('reports.id'))
    action = db.Column(db.String(200))
    performed_by = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
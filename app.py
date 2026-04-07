from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from datetime import datetime, date, timedelta
import json, os, random
from io import BytesIO
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from flask import make_response

app = Flask(__name__)
app.config['SECRET_KEY'] = 'bloodbank-kenya-2024-secure-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bloodbank.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ─── MODELS ──────────────────────────────────────────────────────────────────

class Facility(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    county = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(200))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    users = db.relationship('User', backref='facility', lazy=True)
    inventory = db.relationship('BloodInventory', backref='facility', lazy=True)
    appointments = db.relationship('Appointment', backref='facility', lazy=True)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    first_name = db.Column(db.String(60), nullable=False)
    last_name = db.Column(db.String(60), nullable=False)
    phone = db.Column(db.String(20))
    national_id = db.Column(db.String(20), unique=True)
    role = db.Column(db.String(20), default='donor')  # admin, donor, recipient
    facility_id = db.Column(db.Integer, db.ForeignKey('facility.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    is_approved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Medical info
    blood_type = db.Column(db.String(5))
    date_of_birth = db.Column(db.Date)
    gender = db.Column(db.String(10))
    weight_kg = db.Column(db.Float)
    county = db.Column(db.String(100))
    # Donor medical form
    has_donated_before = db.Column(db.Boolean, default=False)
    last_donation_date = db.Column(db.Date)
    has_chronic_disease = db.Column(db.Boolean, default=False)
    chronic_disease_details = db.Column(db.String(300))
    on_medication = db.Column(db.Boolean, default=False)
    medication_details = db.Column(db.String(300))
    recent_surgery = db.Column(db.Boolean, default=False)
    recent_tattoo = db.Column(db.Boolean, default=False)
    hiv_status = db.Column(db.String(20), default='negative')
    hepatitis_b = db.Column(db.Boolean, default=False)
    hepatitis_c = db.Column(db.Boolean, default=False)
    malaria_history = db.Column(db.Boolean, default=False)
    allergies = db.Column(db.String(300))
    emergency_contact_name = db.Column(db.String(100))
    emergency_contact_phone = db.Column(db.String(20))
    donations = db.relationship('Donation', backref='donor', lazy=True)
    appointments = db.relationship('Appointment', foreign_keys='Appointment.user_id', backref='user', lazy=True)


class MedicalReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    facility_id = db.Column(db.Integer, db.ForeignKey('facility.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    report_type = db.Column(db.String(50), default='general')  # general, pre_donation, post_donation, screening
    content = db.Column(db.Text, nullable=False)
    blood_pressure = db.Column(db.String(20))
    hemoglobin = db.Column(db.Float)
    weight_kg = db.Column(db.Float)
    temperature = db.Column(db.Float)
    pulse = db.Column(db.Integer)
    notes = db.Column(db.Text)
    submitted_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # admin who recorded
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', foreign_keys=[user_id], backref='medical_reports')
    submitter = db.relationship('User', foreign_keys=[submitted_by])

class BloodInventory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    facility_id = db.Column(db.Integer, db.ForeignKey('facility.id'), nullable=False)
    blood_type = db.Column(db.String(5), nullable=False)
    units_available = db.Column(db.Integer, default=0)
    units_reserved = db.Column(db.Integer, default=0)
    expiry_date = db.Column(db.Date)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='available')  # available, critical, expired

    @property
    def units_net(self):
        return self.units_available - self.units_reserved

    @property
    def is_low(self):
        return self.units_available < 5

class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    facility_id = db.Column(db.Integer, db.ForeignKey('facility.id'), nullable=False)
    appointment_date = db.Column(db.Date, nullable=False)
    appointment_time = db.Column(db.String(10))
    type = db.Column(db.String(20), default='donation')  # donation, request
    blood_type_needed = db.Column(db.String(5))
    units_needed = db.Column(db.Integer, default=1)
    reason = db.Column(db.String(300))
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected, completed
    admin_notes = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime)

class Donation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    donor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    facility_id = db.Column(db.Integer, db.ForeignKey('facility.id'), nullable=False)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'), nullable=True)
    blood_type = db.Column(db.String(5))
    units_donated = db.Column(db.Float, default=1.0)
    donation_date = db.Column(db.Date, default=date.today)
    hemoglobin_level = db.Column(db.Float)
    blood_pressure = db.Column(db.String(20))
    notes = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class BloodRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    facility_id = db.Column(db.Integer, db.ForeignKey('facility.id'), nullable=False)
    blood_type = db.Column(db.String(5), nullable=False)
    units_needed = db.Column(db.Integer, nullable=False)
    urgency = db.Column(db.String(20), default='normal')  # critical, urgent, normal
    reason = db.Column(db.String(300))
    status = db.Column(db.String(20), default='pending')
    matched_donor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    requester = db.relationship('User', foreign_keys=[requester_id], backref='blood_requests')
    matched_donor = db.relationship('User', foreign_keys=[matched_donor_id])

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.String(500))
    type = db.Column(db.String(30), default='info')
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ─── HELPERS ─────────────────────────────────────────────────────────────────

BLOOD_COMPATIBILITY = {
    'O-':  ['O-', 'O+', 'A-', 'A+', 'B-', 'B+', 'AB-', 'AB+'],
    'O+':  ['O+', 'A+', 'B+', 'AB+'],
    'A-':  ['A-', 'A+', 'AB-', 'AB+'],
    'A+':  ['A+', 'AB+'],
    'B-':  ['B-', 'B+', 'AB-', 'AB+'],
    'B+':  ['B+', 'AB+'],
    'AB-': ['AB-', 'AB+'],
    'AB+': ['AB+'],
}

def find_compatible_donors(blood_type_needed, facility_id=None, exclude_user_id=None):
    compatible = []
    for donor_type, can_donate_to in BLOOD_COMPATIBILITY.items():
        if blood_type_needed in can_donate_to:
            compatible.append(donor_type)
    query = User.query.filter(User.blood_type.in_(compatible), User.role == 'donor', User.is_approved == True)
    if facility_id:
        query = query.filter(User.facility_id == facility_id)
    if exclude_user_id:
        query = query.filter(User.id != exclude_user_id)
    donors = query.all()
    eligible = []
    for donor in donors:
        last = donor.last_donation_date
        if last is None or (date.today() - last).days >= 90:
            eligible.append(donor)
    return eligible

def predict_stock_shortage(facility_id):
    alerts = []
    inventories = BloodInventory.query.filter_by(facility_id=facility_id).all()
    for inv in inventories:
        if inv.units_available <= 3:
            alerts.append({'blood_type': inv.blood_type, 'units': inv.units_available, 'level': 'critical'})
        elif inv.units_available <= 8:
            alerts.append({'blood_type': inv.blood_type, 'units': inv.units_available, 'level': 'low'})
        if inv.expiry_date and (inv.expiry_date - date.today()).days <= 7:
            alerts.append({'blood_type': inv.blood_type, 'units': inv.units_available, 'level': 'expiring', 'days': (inv.expiry_date - date.today()).days})
    return alerts

def add_notification(user_id, message, ntype='info'):
    n = Notification(user_id=user_id, message=message, type=ntype)
    db.session.add(n)
    db.session.commit()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ─── SEED DATA ────────────────────────────────────────────────────────────────

def seed_database():
    if Facility.query.first():
        return
    facilities = [
        Facility(name="Kenyatta National Hospital Blood Bank", county="Nairobi", address="Hospital Rd, Nairobi", phone="020-2726300", email="knh@health.go.ke", latitude=-1.3006, longitude=36.8074),
        Facility(name="Aga Khan University Hospital", county="Nairobi", address="3rd Parklands Ave, Nairobi", phone="020-3662000", email="info@agakhan.org", latitude=-1.2637, longitude=36.8167),
        Facility(name="Moi Teaching & Referral Hospital", county="Uasin Gishu", address="Nandi Rd, Eldoret", phone="053-2033471", email="mtrh@health.go.ke", latitude=0.5143, longitude=35.2698),
        Facility(name="Coast General Teaching Hospital", county="Mombasa", address="Moi Ave, Mombasa", phone="041-2314201", email="coastgeneral@health.go.ke", latitude=-4.0435, longitude=39.6682),
        Facility(name="Nakuru Level 5 Hospital", county="Nakuru", address="Hospital Rd, Nakuru", phone="051-2212450", email="nakuru@health.go.ke", latitude=-0.2833, longitude=36.0667),
    ]
    for f in facilities:
        db.session.add(f)
    db.session.commit()

    # Admin user
    admin_pw = bcrypt.generate_password_hash('Admin@123').decode('utf-8')
    admin = User(
        email='admin@knh.go.ke', password=admin_pw,
        first_name='System', last_name='Administrator',
        phone='0700000001', national_id='12345678',
        role='admin', facility_id=1, is_approved=True,
        blood_type='O+', gender='Male', county='Nairobi',
        date_of_birth=date(1985, 1, 1), weight_kg=75
    )
    db.session.add(admin)

    # Sample donors
    blood_types = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
    names = [
        ('James', 'Mwangi'), ('Wanjiru', 'Kamau'), ('Omondi', 'Otieno'),
        ('Fatuma', 'Hassan'), ('Kipchoge', 'Ngetich'), ('Grace', 'Achieng'),
        ('Brian', 'Mutua'), ('Aisha', 'Mohamed'), ('Peter', 'Njoroge'), ('Mary', 'Wambui')
    ]
    for i, (fn, ln) in enumerate(names):
        u = User(
            email=f'{fn.lower()}.{ln.lower()}@gmail.com',
            password=bcrypt.generate_password_hash('Donor@123').decode('utf-8'),
            first_name=fn, last_name=ln,
            phone=f'07{random.randint(10000000,99999999)}',
            national_id=f'{random.randint(20000000,39999999)}',
            role='donor', facility_id=random.randint(1, 5), is_approved=True,
            blood_type=random.choice(blood_types),
            gender=random.choice(['Male', 'Female']),
            county=random.choice(['Nairobi', 'Mombasa', 'Kisumu', 'Nakuru', 'Eldoret']),
            date_of_birth=date(1990 + i, random.randint(1,12), random.randint(1,28)),
            weight_kg=random.uniform(55, 90),
            has_donated_before=random.choice([True, False]),
            last_donation_date=date.today() - timedelta(days=random.randint(100, 400)) if i % 2 == 0 else None
        )
        db.session.add(u)

    db.session.commit()

    # Inventory for each facility
    for fac in facilities:
        for bt in blood_types:
            units = random.randint(2, 25)
            inv = BloodInventory(
                facility_id=fac.id, blood_type=bt,
                units_available=units,
                expiry_date=date.today() + timedelta(days=random.randint(5, 42)),
                status='critical' if units < 5 else 'available'
            )
            db.session.add(inv)
    db.session.commit()

# ─── CONTEXT PROCESSOR ───────────────────────────────────────────────────────

@app.context_processor
def inject_globals():
    count = 0
    if current_user.is_authenticated and current_user.role == 'admin':
        # Count pending non-admin users + pending admin accounts (excluding self)
        count = User.query.filter(
            User.facility_id == current_user.facility_id,
            User.is_approved == False,
            User.is_active == True
        ).count()
    return dict(pending_approvals_count=count, today=date.today())

# ─── AUTH ROUTES ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and bcrypt.check_password_hash(user.password, password):
            if not user.is_active:
                return jsonify({'success': False, 'message': 'Account suspended. Contact administrator.'})
            if not user.is_approved:
                return jsonify({'success': False, 'pending': True, 'message': 'Your account is pending approval from another administrator. Please ask a colleague to approve your account in the Users section.'})
            login_user(user)
            return jsonify({'success': True, 'redirect': url_for('dashboard')})
        return jsonify({'success': False, 'message': 'Invalid email or password.'})
    facilities = Facility.query.all()
    return render_template('login.html', facilities=facilities)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.form
        # ── Validate required fields server-side ──────────────────────────────
        required = {'email': 'Email', 'password': 'Password',
                    'first_name': 'First name', 'last_name': 'Last name',
                    'national_id': 'National ID', 'date_of_birth': 'Date of birth',
                    'facility_id': 'Facility'}
        for field, label in required.items():
            if not data.get(field, '').strip():
                return jsonify({'success': False, 'message': f'{label} is required.'})
        email = data.get('email', '').strip().lower()
        if User.query.filter_by(email=email).first():
            return jsonify({'success': False, 'message': 'Email already registered.'})
        nid = data.get('national_id', '').strip()
        if nid and User.query.filter_by(national_id=nid).first():
            return jsonify({'success': False, 'message': 'National ID already registered.'})
        try:
            pw = bcrypt.generate_password_hash(data.get('password')).decode('utf-8')
            dob_str = data.get('date_of_birth')
            dob = datetime.strptime(dob_str, '%Y-%m-%d').date() if dob_str else None
            last_don_str = data.get('last_donation_date')
            last_don = datetime.strptime(last_don_str, '%Y-%m-%d').date() if last_don_str else None
            user = User(
                email=email, password=pw,
                first_name=data.get('first_name', '').strip(),
                last_name=data.get('last_name', '').strip(),
                phone=data.get('phone', '').strip() or None,
                national_id=nid or None,
                role=data.get('role', 'donor'),
                facility_id=int(data.get('facility_id')) if data.get('facility_id') else None,
                blood_type=data.get('blood_type') or None,
                date_of_birth=dob, gender=data.get('gender') or None,
                weight_kg=float(data.get('weight_kg')) if data.get('weight_kg') else None,
                county=data.get('county', '').strip() or None,
                has_donated_before=data.get('has_donated_before') == 'yes',
                last_donation_date=last_don,
                has_chronic_disease=data.get('has_chronic_disease') == 'yes',
                chronic_disease_details=data.get('chronic_disease_details') or None,
                on_medication=data.get('on_medication') == 'yes',
                medication_details=data.get('medication_details') or None,
                recent_surgery=data.get('recent_surgery') == 'yes',
                recent_tattoo=data.get('recent_tattoo') == 'yes',
                hiv_status=data.get('hiv_status', 'negative'),
                hepatitis_b=data.get('hepatitis_b') == 'yes',
                hepatitis_c=data.get('hepatitis_c') == 'yes',
                malaria_history=data.get('malaria_history') == 'yes',
                allergies=data.get('allergies') or None,
                emergency_contact_name=data.get('emergency_contact_name') or None,
                emergency_contact_phone=data.get('emergency_contact_phone') or None,
                is_approved=True
            )
            db.session.add(user)
            db.session.commit()
            if user.facility_id:
                admins = User.query.filter_by(facility_id=user.facility_id, role='admin').all()
                for a in admins:
                    add_notification(a.id, f'New {user.role} registration: {user.first_name} {user.last_name}.', 'info')
            return jsonify({'success': True, 'message': 'Account created! You can now sign in.'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': f'Registration failed: {str(e)}'})
    facilities = Facility.query.all()
    return render_template('register.html', facilities=facilities)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ─── DASHBOARD ────────────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('user_dashboard'))

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('user_dashboard'))
    fid = current_user.facility_id
    total_donors = User.query.filter_by(facility_id=fid, role='donor').count()
    total_recipients = User.query.filter_by(facility_id=fid, role='recipient').count()
    pending_approvals = User.query.filter_by(facility_id=fid, is_approved=False).count()
    pending_appointments = Appointment.query.filter_by(facility_id=fid, status='pending').count()
    inventory = BloodInventory.query.filter_by(facility_id=fid).all()
    total_units = sum(i.units_available for i in inventory)
    alerts = predict_stock_shortage(fid)
    recent_appointments = Appointment.query.filter_by(facility_id=fid).order_by(Appointment.created_at.desc()).limit(5).all()
    recent_donations = Donation.query.filter_by(facility_id=fid).order_by(Donation.created_at.desc()).limit(5).all()
    pending_users = User.query.filter_by(facility_id=fid, is_approved=False).all()
    blood_requests = BloodRequest.query.filter_by(facility_id=fid, status='pending').all()
    notifications = Notification.query.filter_by(user_id=current_user.id, is_read=False).order_by(Notification.created_at.desc()).limit(10).all()
    # Chart data
    inv_labels = [i.blood_type for i in inventory]
    inv_data = [i.units_available for i in inventory]
    # Monthly donations
    months = []
    month_counts = []
    for i in range(5, -1, -1):
        m = date.today().replace(day=1) - timedelta(days=30*i)
        count = Donation.query.filter(
            Donation.facility_id == fid,
            db.extract('month', Donation.donation_date) == m.month,
            db.extract('year', Donation.donation_date) == m.year
        ).count()
        months.append(m.strftime('%b %Y'))
        month_counts.append(count)
    return render_template('admin_dashboard.html',
        total_donors=total_donors, total_recipients=total_recipients,
        pending_approvals=pending_approvals, pending_appointments=pending_appointments,
        inventory=inventory, total_units=total_units, alerts=alerts,
        recent_appointments=recent_appointments, recent_donations=recent_donations,
        pending_users=pending_users, blood_requests=blood_requests,
        notifications=notifications, inv_labels=json.dumps(inv_labels),
        inv_data=json.dumps(inv_data), months=json.dumps(months),
        month_counts=json.dumps(month_counts), facility=current_user.facility
    )

@app.route('/user/dashboard')
@login_required
def user_dashboard():
    my_appointments = Appointment.query.filter_by(user_id=current_user.id).order_by(Appointment.created_at.desc()).all()
    my_donations = Donation.query.filter_by(donor_id=current_user.id).order_by(Donation.donation_date.desc()).all()
    notifications = Notification.query.filter_by(user_id=current_user.id, is_read=False).order_by(Notification.created_at.desc()).limit(5).all()
    facilities = Facility.query.all()
    inventory = BloodInventory.query.filter_by(facility_id=current_user.facility_id).all() if current_user.facility_id else []
    # Eligibility
    eligible = True
    days_until_eligible = 0
    next_eligible_date = date.today()
    if current_user.last_donation_date:
        days_since = (date.today() - current_user.last_donation_date).days
        if days_since < 90:
            eligible = False
            days_until_eligible = 90 - days_since
            next_eligible_date = current_user.last_donation_date + timedelta(days=90)
    # Match score
    my_blood_requests = BloodRequest.query.filter_by(requester_id=current_user.id).order_by(BloodRequest.created_at.desc()).all()
    return render_template('user_dashboard.html',
        my_appointments=my_appointments, my_donations=my_donations,
        notifications=notifications, facilities=facilities,
        inventory=inventory, eligible=eligible,
        days_until_eligible=days_until_eligible,
        next_eligible_date=next_eligible_date,
        my_blood_requests=my_blood_requests
    )

# ─── ADMIN: USER MANAGEMENT ──────────────────────────────────────────────────

@app.route('/admin/users')
@login_required
def admin_users():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    users = User.query.filter_by(facility_id=current_user.facility_id).all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/users/approve/<int:uid>', methods=['POST'])
@login_required
def approve_user(uid):
    if current_user.role != 'admin':
        return jsonify({'success': False})
    user = User.query.get_or_404(uid)
    # Admin accounts can only be approved by a different admin
    if user.role == 'admin' and user.id == current_user.id:
        return jsonify({'success': False, 'message': 'You cannot approve your own admin account.'})
    if user.role == 'admin' and current_user.role != 'admin':
        return jsonify({'success': False, 'message': 'Only another admin can approve admin accounts.'})
    user.is_approved = True
    db.session.commit()
    add_notification(user.id, 'Your account has been approved! You can now log in.', 'success')
    return jsonify({'success': True, 'message': f'{user.first_name} approved.'})

@app.route('/admin/users/reject/<int:uid>', methods=['POST'])
@login_required
def reject_user(uid):
    if current_user.role != 'admin':
        return jsonify({'success': False})
    user = User.query.get_or_404(uid)
    user.is_active = False
    db.session.commit()
    return jsonify({'success': True, 'message': f'{user.first_name} rejected.'})

@app.route('/admin/users/toggle/<int:uid>', methods=['POST'])
@login_required
def toggle_user(uid):
    if current_user.role != 'admin':
        return jsonify({'success': False})
    user = User.query.get_or_404(uid)
    user.is_active = not user.is_active
    db.session.commit()
    status = 'activated' if user.is_active else 'suspended'
    return jsonify({'success': True, 'message': f'User {status}.', 'status': user.is_active})

@app.route('/admin/users/<int:uid>')
@login_required
def user_detail(uid):
    if current_user.role != 'admin':
        return jsonify({'success': False})
    user = User.query.get_or_404(uid)
    return jsonify({
        'id': user.id, 'name': f'{user.first_name} {user.last_name}',
        'email': user.email, 'phone': user.phone, 'national_id': user.national_id,
        'blood_type': user.blood_type, 'role': user.role, 'gender': user.gender,
        'county': user.county, 'weight_kg': user.weight_kg,
        'dob': str(user.date_of_birth) if user.date_of_birth else '',
        'has_chronic_disease': user.has_chronic_disease,
        'chronic_disease_details': user.chronic_disease_details,
        'on_medication': user.on_medication, 'medication_details': user.medication_details,
        'recent_surgery': user.recent_surgery, 'recent_tattoo': user.recent_tattoo,
        'hiv_status': user.hiv_status, 'hepatitis_b': user.hepatitis_b,
        'hepatitis_c': user.hepatitis_c, 'malaria_history': user.malaria_history,
        'allergies': user.allergies, 'has_donated_before': user.has_donated_before,
        'last_donation_date': str(user.last_donation_date) if user.last_donation_date else '',
        'emergency_contact_name': user.emergency_contact_name,
        'emergency_contact_phone': user.emergency_contact_phone,
        'is_approved': user.is_approved, 'is_active': user.is_active,
        'donations_count': len(user.donations)
    })

# ─── APPOINTMENTS ─────────────────────────────────────────────────────────────

@app.route('/appointments/book', methods=['POST'])
@login_required
def book_appointment():
    data = request.form
    appt_date_str = data.get("appointment_date")
    if not appt_date_str:
        return jsonify({"success": False, "message": "Appointment date required."})
    # Facility ID must be explicitly provided
    facility_id_str = data.get("facility_id")
    if not facility_id_str:
        return jsonify({"success": False, "message": "Facility is required."})
    try:
        facility_id = int(facility_id_str)
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid facility."})
    appt_date = datetime.strptime(appt_date_str, "%Y-%m-%d").date()
    appt = Appointment(
        user_id=current_user.id,
        facility_id=facility_id,
        appointment_date=appt_date,
        appointment_time=data.get('appointment_time'),
        type=data.get('type', 'donation'),
        blood_type_needed=data.get('blood_type_needed'),
        units_needed=int(data.get('units_needed', 1)),
        reason=data.get('reason'),
        status='pending'
    )
    db.session.add(appt)
    db.session.commit()
    # Notify admins
    admins = User.query.filter_by(facility_id=appt.facility_id, role='admin').all()
    for a in admins:
        add_notification(a.id, f'New appointment request from {current_user.first_name} {current_user.last_name} on {appt_date}.', 'info')
    return jsonify({'success': True, 'message': 'Appointment booked! Awaiting admin approval.'})

@app.route('/admin/appointments')
@login_required
def admin_appointments():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    appointments = Appointment.query.filter_by(facility_id=current_user.facility_id).order_by(Appointment.created_at.desc()).all()
    return render_template('admin_appointments.html', appointments=appointments)

@app.route('/admin/appointments/<int:aid>/approve', methods=['POST'])
@login_required
def approve_appointment(aid):
    if current_user.role != 'admin':
        return jsonify({'success': False})
    appt = Appointment.query.get_or_404(aid)
    appt.status = 'approved'
    appt.reviewed_by = current_user.id
    appt.reviewed_at = datetime.utcnow()
    appt.admin_notes = request.form.get('notes', '')
    db.session.commit()
    add_notification(appt.user_id, f'Your appointment on {appt.appointment_date} has been APPROVED.', 'success')
    return jsonify({'success': True, 'message': 'Appointment approved.'})

@app.route('/admin/appointments/<int:aid>/reject', methods=['POST'])
@login_required
def reject_appointment(aid):
    if current_user.role != 'admin':
        return jsonify({'success': False})
    appt = Appointment.query.get_or_404(aid)
    appt.status = 'rejected'
    appt.reviewed_by = current_user.id
    appt.reviewed_at = datetime.utcnow()
    appt.admin_notes = request.form.get('notes', '')
    db.session.commit()
    add_notification(appt.user_id, f'Your appointment on {appt.appointment_date} was not approved. Reason: {appt.admin_notes}', 'warning')
    return jsonify({'success': True, 'message': 'Appointment rejected.'})

@app.route('/admin/appointments/<int:aid>/complete', methods=['POST'])
@login_required
def complete_appointment(aid):
    if current_user.role != 'admin':
        return jsonify({'success': False})
    appt = Appointment.query.get_or_404(aid)
    appt.status = 'completed'
    db.session.commit()
    if appt.type == 'donation':
        # Add donation record + update inventory
        donation = Donation(
            donor_id=appt.user_id,
            facility_id=appt.facility_id,
            appointment_id=appt.id,
            blood_type=appt.user.blood_type,
            units_donated=1.0,
            donation_date=date.today()
        )
        db.session.add(donation)
        # Update inventory
        inv = BloodInventory.query.filter_by(facility_id=appt.facility_id, blood_type=appt.user.blood_type).first()
        if inv:
            inv.units_available += 1
            inv.last_updated = datetime.utcnow()
            inv.status = 'available' if inv.units_available >= 5 else 'critical'
        else:
            inv = BloodInventory(
                facility_id=appt.facility_id, blood_type=appt.user.blood_type,
                units_available=1, expiry_date=date.today() + timedelta(days=42)
            )
            db.session.add(inv)
        # Update donor's last donation
        appt.user.last_donation_date = date.today()
        db.session.commit()
        add_notification(appt.user_id, f'Thank you for donating blood! Your donation has been recorded.', 'success')
    return jsonify({'success': True, 'message': 'Appointment completed.'})

# ─── INVENTORY ────────────────────────────────────────────────────────────────

@app.route('/admin/inventory')
@login_required
def admin_inventory():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    inventory = BloodInventory.query.filter_by(facility_id=current_user.facility_id).order_by(BloodInventory.blood_type).all()
    alerts = predict_stock_shortage(current_user.facility_id)
    all_facilities = Facility.query.all()
    return render_template('admin_inventory.html', inventory=inventory, alerts=alerts, all_facilities=all_facilities, today=date.today())

@app.route('/admin/inventory/update', methods=['POST'])
@login_required
def update_inventory():
    if current_user.role != 'admin':
        return jsonify({'success': False})
    data = request.form
    inv_id = data.get('inv_id')
    if inv_id:
        inv = BloodInventory.query.get(int(inv_id))
    else:
        inv = BloodInventory.query.filter_by(
            facility_id=current_user.facility_id,
            blood_type=data.get('blood_type')
        ).first()
        if not inv:
            inv = BloodInventory(facility_id=current_user.facility_id, blood_type=data.get('blood_type'))
            db.session.add(inv)
    inv.units_available = int(data.get('units_available', inv.units_available))
    exp_str = data.get('expiry_date')
    if exp_str:
        inv.expiry_date = datetime.strptime(exp_str, '%Y-%m-%d').date()
    inv.last_updated = datetime.utcnow()
    inv.status = 'critical' if inv.units_available < 5 else 'available'
    db.session.commit()
    return jsonify({'success': True, 'message': 'Inventory updated.'})

@app.route('/admin/inventory/dispense', methods=['POST'])
@login_required
def dispense_blood():
    if current_user.role != 'admin':
        return jsonify({'success': False})
    data = request.form
    units = int(data.get('units_to_dispense') or data.get('units') or 1)
    inventory_id = data.get('inventory_id')
    blood_type = data.get('blood_type')
    if inventory_id:
        inv = BloodInventory.query.get(int(inventory_id))
    else:
        inv = BloodInventory.query.filter_by(
            facility_id=current_user.facility_id,
            blood_type=blood_type
        ).first()
    if not inv or inv.units_available < units:
        return jsonify({'success': False, 'message': 'Insufficient units available.'})
    inv.units_available -= units
    inv.last_updated = datetime.utcnow()
    inv.status = 'critical' if inv.units_available < 5 else 'available'
    db.session.commit()
    return jsonify({'success': True, 'message': f'Dispensed {units} unit(s) of {inv.blood_type}.'})

# ─── BLOOD MATCHING ───────────────────────────────────────────────────────────

@app.route('/match/donors', methods=['POST'])
@login_required
def match_donors():
    data = request.get_json(silent=True) or request.form
    blood_type = data.get('blood_type')
    fid = data.get('facility_id')
    facility_id = int(fid) if fid else current_user.facility_id
    donors = find_compatible_donors(blood_type, facility_id, exclude_user_id=current_user.id)
    result = []
    for d in donors:
        last_don = str(d.last_donation_date) if d.last_donation_date else 'Never'
        days_since = (date.today() - d.last_donation_date).days if d.last_donation_date else 9999
        score = min(100, int((days_since / 365) * 100)) if days_since < 9999 else 100
        result.append({
            'id': d.id, 'name': f'{d.first_name} {d.last_name}',
            'blood_type': d.blood_type, 'phone': d.phone,
            'county': d.county, 'last_donation': last_don,
            'match_score': score
        })
    result.sort(key=lambda x: x['match_score'], reverse=True)
    return jsonify({'success': True, 'donors': result})

@app.route('/blood-request', methods=['POST'])
@login_required
def create_blood_request():
    data = request.form
    # Facility ID must be explicitly provided
    facility_id_str = data.get('facility_id')
    if not facility_id_str:
        return jsonify({'success': False, 'message': 'Facility is required.'})
    try:
        facility_id = int(facility_id_str)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Invalid facility.'})
    req = BloodRequest(
        requester_id=current_user.id,
        facility_id=facility_id,
        blood_type=data.get('blood_type'),
        units_needed=int(data.get('units_needed', 1)),
        urgency=data.get('urgency', 'normal'),
        reason=data.get('reason')
    )
    db.session.add(req)
    db.session.commit()
    admins = User.query.filter_by(facility_id=req.facility_id, role='admin').all()
    for a in admins:
        add_notification(a.id, f'BLOOD REQUEST: {req.blood_type} ({req.units_needed} units) - {req.urgency.upper()} by {current_user.first_name}.', 'warning' if req.urgency != 'critical' else 'error')
    return jsonify({'success': True, 'message': 'Blood request submitted!'})

@app.route('/admin/blood-requests')
@login_required
def admin_blood_requests():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    requests = BloodRequest.query.filter_by(facility_id=current_user.facility_id).order_by(BloodRequest.created_at.desc()).all()
    return render_template('admin_blood_requests.html', requests=requests)

@app.route('/admin/blood-requests/<int:rid>/fulfill', methods=['POST'])
@login_required
def fulfill_request(rid):
    if current_user.role != 'admin':
        return jsonify({'success': False})
    req = BloodRequest.query.get_or_404(rid)
    units = int(request.form.get('units', req.units_needed))
    inv = BloodInventory.query.filter_by(facility_id=req.facility_id, blood_type=req.blood_type).first()
    if not inv or inv.units_available < units:
        return jsonify({'success': False, 'message': 'Insufficient inventory.'})
    inv.units_available -= units
    inv.last_updated = datetime.utcnow()
    req.status = 'fulfilled'
    db.session.commit()
    add_notification(req.requester_id, f'Your blood request for {units} unit(s) of {req.blood_type} has been fulfilled!', 'success')
    return jsonify({'success': True, 'message': 'Request fulfilled.'})

@app.route('/admin/blood-requests/<int:rid>/reject', methods=['POST'])
@login_required
def reject_blood_request(rid):
    if current_user.role != 'admin':
        return jsonify({'success': False})
    req = BloodRequest.query.get_or_404(rid)
    reason = request.form.get('reason', '').strip()
    req.status = 'rejected'
    db.session.commit()
    msg = f'Your blood request for {req.units_needed} unit(s) of {req.blood_type} has been rejected.'
    if reason:
        msg += f' Reason: {reason}'
    add_notification(req.requester_id, msg, 'warning')
    return jsonify({'success': True, 'message': 'Request rejected.'})

# ─── NOTIFICATIONS ────────────────────────────────────────────────────────────

@app.route('/notifications/mark-read', methods=['POST'])
@login_required
def mark_notifications_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/notifications')
@login_required
def get_notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(20).all()
    return jsonify([{
        'id': n.id, 'message': n.message, 'type': n.type,
        'is_read': n.is_read, 'created_at': n.created_at.strftime('%d %b %Y %H:%M')
    } for n in notifs])

@app.route('/api/stats')
@login_required
def api_stats():
    if current_user.role != 'admin':
        return jsonify({})
    fid = current_user.facility_id
    return jsonify({
        'total_donors': User.query.filter_by(facility_id=fid, role='donor').count(),
        'total_units': sum(i.units_available for i in BloodInventory.query.filter_by(facility_id=fid).all()),
        'pending_appointments': Appointment.query.filter_by(facility_id=fid, status='pending').count(),
        'alerts': predict_stock_shortage(fid)
    })

# ─── PROFILE ──────────────────────────────────────────────────────────────────

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.phone = request.form.get('phone', current_user.phone)
        current_user.county = request.form.get('county', current_user.county)
        current_user.emergency_contact_name = request.form.get('emergency_contact_name')
        current_user.emergency_contact_phone = request.form.get('emergency_contact_phone')
        db.session.commit()
        return jsonify({'success': True, 'message': 'Profile updated.'})
    return render_template('profile.html')

# ─── PDF HELPERS ─────────────────────────────────────────────────────────────

def pdf_header_footer(canvas_obj, doc, title, facility_name):
    canvas_obj.saveState()
    w, h = doc.pagesize
    # Header bar
    canvas_obj.setFillColor(colors.HexColor('#C8102E'))
    canvas_obj.rect(0, h - 50, w, 50, fill=1, stroke=0)
    canvas_obj.setFillColor(colors.white)
    canvas_obj.setFont('Helvetica-Bold', 14)
    canvas_obj.drawString(1.5*cm, h - 32, 'HemoLink Kenya')
    canvas_obj.setFont('Helvetica', 10)
    canvas_obj.drawRightString(w - 1.5*cm, h - 32, title)
    # Subheader
    canvas_obj.setFillColor(colors.HexColor('#1a1a1a'))
    canvas_obj.setFont('Helvetica', 8)
    canvas_obj.drawString(1.5*cm, h - 62, f'Facility: {facility_name}   |   Generated: {date.today().strftime("%d %B %Y")}')
    # Footer
    canvas_obj.setFillColor(colors.HexColor('#888888'))
    canvas_obj.setFont('Helvetica', 8)
    canvas_obj.drawString(1.5*cm, 18, 'HemoLink Blood Bank Management System — Confidential')
    canvas_obj.drawRightString(w - 1.5*cm, 18, f'Page {doc.page}')
    canvas_obj.setStrokeColor(colors.HexColor('#dddddd'))
    canvas_obj.line(1.5*cm, 28, w - 1.5*cm, 28)
    canvas_obj.restoreState()

def make_table_style(header_color='#C8102E'):
    return TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(header_color)),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#dddddd')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ])

def build_pdf(title, facility_name, story, landscape_mode=False):
    buf = BytesIO()
    pagesize = landscape(A4) if landscape_mode else A4
    doc = SimpleDocTemplate(buf, pagesize=pagesize,
        topMargin=70, bottomMargin=45, leftMargin=1.5*cm, rightMargin=1.5*cm)
    doc.build(story, onFirstPage=lambda c, d: pdf_header_footer(c, d, title, facility_name),
              onLaterPages=lambda c, d: pdf_header_footer(c, d, title, facility_name))
    buf.seek(0)
    return buf

# ─── PDF EXPORT ROUTES ────────────────────────────────────────────────────────

@app.route('/admin/export/inventory')
@login_required
def export_inventory_pdf():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    fid = current_user.facility_id
    facility = current_user.facility
    inventory = BloodInventory.query.filter_by(facility_id=fid).order_by(BloodInventory.blood_type).all()
    alerts = predict_stock_shortage(fid)
    alert_types = {a['blood_type']: a['level'] for a in alerts}

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('title', fontSize=16, fontName='Helvetica-Bold', spaceAfter=4, textColor=colors.HexColor('#C8102E'))
    sub_style = ParagraphStyle('sub', fontSize=9, fontName='Helvetica', textColor=colors.HexColor('#666666'), spaceAfter=16)
    label_style = ParagraphStyle('label', fontSize=10, fontName='Helvetica-Bold', spaceAfter=8, textColor=colors.HexColor('#1a1a1a'))

    story = [
        Paragraph('Blood Inventory Report', title_style),
        Paragraph(f'{facility.name} &nbsp;|&nbsp; {facility.county} County', sub_style),
        HRFlowable(width='100%', thickness=1, color=colors.HexColor('#C8102E'), spaceAfter=16),
    ]

    # Summary boxes row
    total_units = sum(i.units_available for i in inventory)
    critical = sum(1 for i in inventory if alert_types.get(i.blood_type) == 'critical')
    low = sum(1 for i in inventory if alert_types.get(i.blood_type) == 'low')
    expiring = sum(1 for i in inventory if alert_types.get(i.blood_type) == 'expiring')

    summary_data = [['Total Units', 'Blood Types', 'Critical Stock', 'Low Stock', 'Expiring Soon'],
                    [str(total_units), str(len(inventory)), str(critical), str(low), str(expiring)]]
    summary_tbl = Table(summary_data, colWidths=[3.5*cm]*5)
    summary_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f5f5f5')),
        ('BACKGROUND', (0,1), (-1,1), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,0), 8),
        ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#888888')),
        ('FONTNAME', (0,1), (-1,1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,1), (-1,1), 16),
        ('TEXTCOLOR', (0,1), (-1,1), colors.HexColor('#C8102E')),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#dddddd')),
        ('INNERGRID', (0,0), (-1,-1), 0.3, colors.HexColor('#eeeeee')),
    ]))
    story += [summary_tbl, Spacer(1, 20), Paragraph('Inventory Detail', label_style)]

    headers = ['Blood Type', 'Units Available', 'Status', 'Expiry Date', 'Last Updated', 'Alert']
    rows = [headers]
    for inv in inventory:
        alert = alert_types.get(inv.blood_type, '—').upper() if inv.blood_type in alert_types else '✓ OK'
        rows.append([
            inv.blood_type,
            str(inv.units_available),
            inv.status.title(),
            inv.expiry_date.strftime('%d %b %Y') if inv.expiry_date else '—',
            inv.last_updated.strftime('%d %b %Y') if inv.last_updated else '—',
            alert
        ])
    tbl = Table(rows, colWidths=[2.5*cm, 3.5*cm, 3*cm, 3.5*cm, 4*cm, 3*cm])
    tbl.setStyle(make_table_style())
    # Colour critical/low rows
    for i, inv in enumerate(inventory, 1):
        lvl = alert_types.get(inv.blood_type)
        if lvl == 'critical':
            tbl.setStyle(TableStyle([('BACKGROUND', (0,i), (-1,i), colors.HexColor('#fff0f0'))]))
        elif lvl in ('low','expiring'):
            tbl.setStyle(TableStyle([('BACKGROUND', (0,i), (-1,i), colors.HexColor('#fffbe6'))]))
    story.append(tbl)

    buf = build_pdf('Inventory Report', facility.name, story)
    resp = make_response(buf.read())
    resp.headers['Content-Type'] = 'application/pdf'
    resp.headers['Content-Disposition'] = f'attachment; filename=inventory_{date.today()}.pdf'
    return resp


@app.route('/admin/export/donors')
@login_required
def export_donors_pdf():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    fid = current_user.facility_id
    facility = current_user.facility
    donors = User.query.filter_by(facility_id=fid, role='donor').order_by(User.last_name).all()

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('title', fontSize=16, fontName='Helvetica-Bold', spaceAfter=4, textColor=colors.HexColor('#C8102E'))
    sub_style = ParagraphStyle('sub', fontSize=9, fontName='Helvetica', textColor=colors.HexColor('#666666'), spaceAfter=16)
    label_style = ParagraphStyle('label', fontSize=10, fontName='Helvetica-Bold', spaceAfter=8, textColor=colors.HexColor('#1a1a1a'))

    story = [
        Paragraph('Donor Registry Report', title_style),
        Paragraph(f'{facility.name} &nbsp;|&nbsp; {len(donors)} registered donors', sub_style),
        HRFlowable(width='100%', thickness=1, color=colors.HexColor('#C8102E'), spaceAfter=16),
        Paragraph('Registered Donors', label_style),
    ]

    headers = ['Name', 'Blood Type', 'County', 'Phone', 'Last Donation', 'Status', 'Eligible']
    rows = [headers]
    for d in donors:
        days = (date.today() - d.last_donation_date).days if d.last_donation_date else 999
        eligible = 'Yes' if days >= 90 else f'No ({90-days}d)'
        rows.append([
            f'{d.first_name} {d.last_name}',
            d.blood_type or '—',
            d.county or '—',
            d.phone or '—',
            d.last_donation_date.strftime('%d %b %Y') if d.last_donation_date else 'Never',
            'Approved' if d.is_approved else 'Pending',
            eligible
        ])

    tbl = Table(rows, colWidths=[4*cm, 2.2*cm, 2.8*cm, 3.2*cm, 3*cm, 2.5*cm, 2.3*cm])
    tbl.setStyle(make_table_style())
    story.append(tbl)

    buf = build_pdf('Donor Registry', facility.name, story)
    resp = make_response(buf.read())
    resp.headers['Content-Type'] = 'application/pdf'
    resp.headers['Content-Disposition'] = f'attachment; filename=donors_{date.today()}.pdf'
    return resp


@app.route('/admin/export/appointments')
@login_required
def export_appointments_pdf():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    fid = current_user.facility_id
    facility = current_user.facility
    appointments = Appointment.query.filter_by(facility_id=fid).order_by(Appointment.appointment_date.desc()).limit(100).all()

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('title', fontSize=16, fontName='Helvetica-Bold', spaceAfter=4, textColor=colors.HexColor('#C8102E'))
    sub_style = ParagraphStyle('sub', fontSize=9, fontName='Helvetica', textColor=colors.HexColor('#666666'), spaceAfter=16)
    label_style = ParagraphStyle('label', fontSize=10, fontName='Helvetica-Bold', spaceAfter=8, textColor=colors.HexColor('#1a1a1a'))

    pending = sum(1 for a in appointments if a.status == 'pending')
    completed = sum(1 for a in appointments if a.status == 'completed')
    rejected = sum(1 for a in appointments if a.status == 'rejected')

    story = [
        Paragraph('Appointments Report', title_style),
        Paragraph(f'{facility.name} &nbsp;|&nbsp; Last 100 appointments', sub_style),
        HRFlowable(width='100%', thickness=1, color=colors.HexColor('#C8102E'), spaceAfter=16),
    ]

    summary_data = [['Total', 'Pending', 'Completed', 'Rejected'],
                    [str(len(appointments)), str(pending), str(completed), str(rejected)]]
    summary_tbl = Table(summary_data, colWidths=[4.5*cm]*4)
    summary_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f5f5f5')),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica'), ('FONTSIZE', (0,0), (-1,0), 8),
        ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#888888')),
        ('FONTNAME', (0,1), (-1,1), 'Helvetica-Bold'), ('FONTSIZE', (0,1), (-1,1), 18),
        ('TEXTCOLOR', (0,1), (-1,1), colors.HexColor('#C8102E')),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#dddddd')),
        ('INNERGRID', (0,0), (-1,-1), 0.3, colors.HexColor('#eeeeee')),
    ]))
    story += [summary_tbl, Spacer(1, 20), Paragraph('Appointment Records', label_style)]

    headers = ['Patient', 'Type', 'Date', 'Time', 'Blood Type', 'Status', 'Notes']
    rows = [headers]
    for a in appointments:
        rows.append([
            f'{a.user.first_name} {a.user.last_name}',
            a.type.title(),
            a.appointment_date.strftime('%d %b %Y'),
            a.appointment_time or '—',
            a.blood_type_needed or a.user.blood_type or '—',
            a.status.title(),
            (a.admin_notes[:40] + '...') if a.admin_notes and len(a.admin_notes) > 40 else (a.admin_notes or '—')
        ])

    tbl = Table(rows, colWidths=[4*cm, 2*cm, 3*cm, 2*cm, 2.5*cm, 2.5*cm, 4*cm])
    tbl.setStyle(make_table_style())
    story.append(tbl)

    buf = build_pdf('Appointments Report', facility.name, story, landscape_mode=True)
    resp = make_response(buf.read())
    resp.headers['Content-Type'] = 'application/pdf'
    resp.headers['Content-Disposition'] = f'attachment; filename=appointments_{date.today()}.pdf'
    return resp


@app.route('/admin/export/blood-requests')
@login_required
def export_blood_requests_pdf():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    fid = current_user.facility_id
    facility = current_user.facility
    requests_list = BloodRequest.query.filter_by(facility_id=fid).order_by(BloodRequest.created_at.desc()).all()

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('title', fontSize=16, fontName='Helvetica-Bold', spaceAfter=4, textColor=colors.HexColor('#C8102E'))
    sub_style = ParagraphStyle('sub', fontSize=9, fontName='Helvetica', textColor=colors.HexColor('#666666'), spaceAfter=16)
    label_style = ParagraphStyle('label', fontSize=10, fontName='Helvetica-Bold', spaceAfter=8, textColor=colors.HexColor('#1a1a1a'))

    story = [
        Paragraph('Blood Requests Report', title_style),
        Paragraph(f'{facility.name} &nbsp;|&nbsp; {len(requests_list)} total requests', sub_style),
        HRFlowable(width='100%', thickness=1, color=colors.HexColor('#C8102E'), spaceAfter=16),
        Paragraph('Blood Request Records', label_style),
    ]

    headers = ['Patient', 'Blood Type', 'Units', 'Urgency', 'Reason', 'Date', 'Status']
    rows = [headers]
    for r in requests_list:
        rows.append([
            f'{r.requester.first_name} {r.requester.last_name}',
            r.blood_type,
            str(r.units_needed),
            r.urgency.title(),
            (r.reason[:35] + '...') if r.reason and len(r.reason) > 35 else (r.reason or '—'),
            r.created_at.strftime('%d %b %Y'),
            r.status.title()
        ])

    tbl = Table(rows, colWidths=[4*cm, 2.5*cm, 1.8*cm, 2.5*cm, 5*cm, 3*cm, 2.5*cm])
    tbl.setStyle(make_table_style())
    # Highlight critical rows
    for i, r in enumerate(requests_list, 1):
        if r.urgency == 'critical':
            tbl.setStyle(TableStyle([('BACKGROUND', (0,i), (-1,i), colors.HexColor('#fff0f0'))]))
    story.append(tbl)

    buf = build_pdf('Blood Requests Report', facility.name, story, landscape_mode=True)
    resp = make_response(buf.read())
    resp.headers['Content-Type'] = 'application/pdf'
    resp.headers['Content-Disposition'] = f'attachment; filename=blood_requests_{date.today()}.pdf'
    return resp



# ─── FULL SYSTEM REPORT PDF ──────────────────────────────────────────────────

@app.route('/admin/export/full-report')
@login_required
def export_full_report_pdf():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    fid = current_user.facility_id
    facility = current_user.facility

    from reportlab.platypus import PageBreak as PB

    RED   = colors.HexColor('#C8102E')
    DARK  = colors.HexColor('#1a1a1a')
    GRAY  = colors.HexColor('#888888')
    LGRAY = colors.HexColor('#f5f5f5')
    WARN  = colors.HexColor('#fffbe6')
    CRIT  = colors.HexColor('#fff0f0')
    GREEN = colors.HexColor('#f0fdf4')

    def sec(text, num):
        return Paragraph(f'{num}. {text}', ParagraphStyle(f's{num}',
            fontSize=12, fontName='Helvetica-Bold', spaceAfter=4, spaceBefore=14,
            textColor=RED, borderPad=0))

    def note(text):
        return Paragraph(text, ParagraphStyle('note', fontSize=8, fontName='Helvetica',
            textColor=GRAY, spaceAfter=8))

    def hr():
        return HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#e0e0e0'), spaceAfter=10)

    def tbl(rows, widths, highlights=None):
        t = Table(rows, colWidths=widths, repeatRows=1)
        t.setStyle(make_table_style())
        if highlights:
            for i, col in highlights:
                t.setStyle(TableStyle([('BACKGROUND',(0,i),(-1,i),col)]))
        return t

    # ── Data fetch ─────────────────────────────────────────────────────────────
    donors     = User.query.filter_by(facility_id=fid, role='donor').order_by(User.last_name).all()
    recipients = User.query.filter_by(facility_id=fid, role='recipient').order_by(User.last_name).all()
    inv        = BloodInventory.query.filter_by(facility_id=fid).order_by(BloodInventory.blood_type).all()
    appts      = Appointment.query.filter_by(facility_id=fid).order_by(Appointment.appointment_date.desc()).all()
    reqs       = BloodRequest.query.filter_by(facility_id=fid).order_by(BloodRequest.created_at.desc()).all()
    donations  = Donation.query.filter_by(facility_id=fid).order_by(Donation.donation_date.desc()).all()
    alerts     = predict_stock_shortage(fid)
    alert_map  = {a['blood_type']: a['level'] for a in alerts}

    total_units = sum(i.units_available for i in inv)
    eligible_donors = sum(1 for d in donors if d.last_donation_date is None or (date.today()-d.last_donation_date).days >= 90)

    story = []

    # ══ COVER PAGE ════════════════════════════════════════════════════════════
    story.append(Spacer(1, 2.5*cm))
    story.append(Paragraph('HemoLink Kenya', ParagraphStyle('ct', fontSize=30, fontName='Helvetica-Bold',
        textColor=RED, alignment=TA_CENTER, spaceAfter=6)))
    story.append(Paragraph('Full System Report', ParagraphStyle('cs', fontSize=15, fontName='Helvetica',
        textColor=DARK, alignment=TA_CENTER, spaceAfter=10)))
    story.append(HRFlowable(width='50%', thickness=1.5, color=RED, hAlign='CENTER', spaceAfter=14))
    story.append(Paragraph(facility.name, ParagraphStyle('cf', fontSize=12, fontName='Helvetica-Bold',
        alignment=TA_CENTER, spaceAfter=4)))
    story.append(Paragraph(f'{facility.county} County  ·  {facility.address or ""}',
        ParagraphStyle('cfa', fontSize=9, fontName='Helvetica', textColor=GRAY, alignment=TA_CENTER, spaceAfter=4)))
    story.append(Paragraph(f'Generated: {date.today().strftime("%A, %d %B %Y")}',
        ParagraphStyle('cg', fontSize=9, fontName='Helvetica', textColor=GRAY, alignment=TA_CENTER, spaceAfter=24)))

    # Cover summary box
    cover_stats = Table([
        ['Donors', 'Recipients', 'Blood Units', 'Appointments', 'Requests'],
        [str(len(donors)), str(len(recipients)), str(total_units), str(len(appts)), str(len(reqs))]
    ], colWidths=[3.8*cm]*5)
    cover_stats.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),LGRAY),
        ('FONTNAME',(0,0),(-1,0),'Helvetica'), ('FONTSIZE',(0,0),(-1,0),8),
        ('TEXTCOLOR',(0,0),(-1,0),GRAY), ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('TOPPADDING',(0,0),(-1,-1),8), ('BOTTOMPADDING',(0,0),(-1,-1),8),
        ('FONTNAME',(0,1),(-1,1),'Helvetica-Bold'), ('FONTSIZE',(0,1),(-1,1),18),
        ('TEXTCOLOR',(0,1),(-1,1),RED),
        ('BOX',(0,0),(-1,-1),0.5,colors.HexColor('#dddddd')),
        ('INNERGRID',(0,0),(-1,-1),0.3,colors.HexColor('#eeeeee')),
    ]))
    story += [cover_stats, Spacer(1, 16)]

    # Table of contents
    toc_style = ParagraphStyle('toc', fontSize=9, fontName='Helvetica', textColor=DARK, spaceAfter=3, leftIndent=10)
    story.append(Paragraph('Contents', ParagraphStyle('toch', fontSize=10, fontName='Helvetica-Bold',
        textColor=DARK, spaceAfter=8)))
    for line in [
        '1. System Overview', '2. Blood Inventory', '3. Donor Registry',
        '4. Recipient Registry', '5. Donation History', '6. Appointments', '7. Blood Requests'
    ]:
        story.append(Paragraph(line, toc_style))
    story.append(PB())

    # ══ 1. OVERVIEW ══════════════════════════════════════════════════════════
    story.append(sec('System Overview', 1))
    story.append(hr())
    story.append(note(f'Facility: {facility.name}  ·  Contact: {facility.phone or "—"}  ·  Email: {facility.email or "—"}'))

    ov_rows = [['Category', 'Total', 'Active / Approved', 'Pending'],
        ['Donors', str(len(donors)),
         str(sum(1 for d in donors if d.is_approved)),
         str(sum(1 for d in donors if not d.is_approved))],
        ['Recipients', str(len(recipients)),
         str(sum(1 for r in recipients if r.is_approved)),
         str(sum(1 for r in recipients if not r.is_approved))],
        ['Eligible Donors (90-day)', str(eligible_donors), '—', '—'],
        ['Blood Units in Stock', str(total_units), '—', f'{len(alerts)} alerts'],
        ['Appointments', str(len(appts)),
         str(sum(1 for a in appts if a.status=='completed')),
         str(sum(1 for a in appts if a.status=='pending'))],
        ['Blood Requests', str(len(reqs)),
         str(sum(1 for r in reqs if r.status in ('fulfilled','approved'))),
         str(sum(1 for r in reqs if r.status=='pending'))],
        ['Donations Recorded', str(len(donations)), '—', '—'],
    ]
    story += [tbl(ov_rows, [5*cm, 3*cm, 4*cm, 4*cm]), Spacer(1,12)]

    # ══ 2. BLOOD INVENTORY ═══════════════════════════════════════════════════
    story.append(PB())
    story.append(sec('Blood Inventory', 2))
    story.append(hr())
    story.append(note(f'{len(inv)} blood types tracked  ·  Total: {total_units} units  ·  Alerts: {len(alerts)}'))

    inv_rows = [['Blood Type', 'Units Available', 'Status', 'Alert Level', 'Expiry Date', 'Last Updated']]
    inv_highlights = []
    for idx, i in enumerate(inv, 1):
        lvl = alert_map.get(i.blood_type)
        alert_label = lvl.upper() if lvl else 'OK'
        inv_rows.append([
            i.blood_type, str(i.units_available), i.status.title(), alert_label,
            i.expiry_date.strftime('%d %b %Y') if i.expiry_date else '—',
            i.last_updated.strftime('%d %b %Y') if i.last_updated else '—'
        ])
        if lvl == 'critical':   inv_highlights.append((idx, CRIT))
        elif lvl in ('low','expiring'): inv_highlights.append((idx, WARN))
        else:                   inv_highlights.append((idx, GREEN))
    story += [tbl(inv_rows, [2.5*cm, 3*cm, 2.5*cm, 2.5*cm, 3.5*cm, 4*cm], inv_highlights), Spacer(1,12)]

    # ══ 3. DONOR REGISTRY ════════════════════════════════════════════════════
    story.append(PB())
    story.append(sec('Donor Registry', 3))
    story.append(hr())
    story.append(note(f'{len(donors)} donors registered  ·  {eligible_donors} currently eligible to donate'))

    d_rows = [['Name', 'Blood Type', 'Gender', 'County', 'Phone', 'Last Donation', 'Eligible', 'Status']]
    for d in donors:
        days = (date.today() - d.last_donation_date).days if d.last_donation_date else 999
        eligible = 'Yes' if days >= 90 else f'No ({90-days}d)'
        d_rows.append([
            f'{d.first_name} {d.last_name}',
            d.blood_type or '—',
            (d.gender or '—').title(),
            d.county or '—',
            d.phone or '—',
            d.last_donation_date.strftime('%d %b %Y') if d.last_donation_date else 'Never',
            eligible,
            'Approved' if d.is_approved else 'Pending'
        ])
    story += [tbl(d_rows, [3.8*cm, 2*cm, 1.8*cm, 2.5*cm, 2.8*cm, 2.8*cm, 2.2*cm, 2.1*cm]), Spacer(1,12)]

    # Donor medical summary
    story.append(Paragraph('Medical Screening Summary', ParagraphStyle('ms',
        fontSize=10, fontName='Helvetica-Bold', textColor=DARK, spaceAfter=6, spaceBefore=8)))
    med_rows = [['Name', 'HIV', 'Hep B', 'Hep C', 'Malaria', 'Surgery', 'Tattoo', 'Chronic', 'Allergies']]
    for d in donors:
        med_rows.append([
            f'{d.first_name} {d.last_name}',
            (d.hiv_status or 'neg').title(),
            'Yes' if d.hepatitis_b else 'No',
            'Yes' if d.hepatitis_c else 'No',
            'Yes' if d.malaria_history else 'No',
            'Yes' if d.recent_surgery else 'No',
            'Yes' if d.recent_tattoo else 'No',
            'Yes' if d.has_chronic_disease else 'No',
            (d.allergies[:20]+'…') if d.allergies and len(d.allergies)>20 else (d.allergies or '—')
        ])
    story += [tbl(med_rows, [3.5*cm, 1.5*cm, 1.5*cm, 1.5*cm, 1.8*cm, 1.8*cm, 1.8*cm, 1.8*cm, 4.8*cm])]

    # ══ 4. RECIPIENT REGISTRY ════════════════════════════════════════════════
    story.append(PB())
    story.append(sec('Recipient Registry', 4))
    story.append(hr())
    story.append(note(f'{len(recipients)} recipients registered at this facility'))

    if recipients:
        r_rows = [['Name', 'Blood Type', 'Gender', 'County', 'Phone', 'Date of Birth', 'Status', 'Registered']]
        for r in recipients:
            r_rows.append([
                f'{r.first_name} {r.last_name}',
                r.blood_type or '—',
                (r.gender or '—').title(),
                r.county or '—',
                r.phone or '—',
                r.date_of_birth.strftime('%d %b %Y') if r.date_of_birth else '—',
                'Approved' if r.is_approved else 'Pending',
                r.created_at.strftime('%d %b %Y')
            ])
        story.append(tbl(r_rows, [3.5*cm, 2*cm, 1.8*cm, 2.5*cm, 2.8*cm, 2.8*cm, 2.2*cm, 2.4*cm]))
    else:
        story.append(Paragraph('No recipients registered at this facility.', ParagraphStyle('empty',
            fontSize=9, fontName='Helvetica', textColor=GRAY)))
    story.append(Spacer(1,12))

    # ══ 5. DONATION HISTORY ══════════════════════════════════════════════════
    story.append(PB())
    story.append(sec('Donation History', 5))
    story.append(hr())
    story.append(note(f'{len(donations)} donations recorded  ·  Most recent 100 shown'))
    recent_donations = donations[:100]
    if recent_donations:
        don_rows = [['Donor', 'Blood Type', 'Units', 'Date', 'Haemoglobin']]
        for d in recent_donations:
            don_rows.append([
                f'{d.donor.first_name} {d.donor.last_name}' if d.donor else '—',
                d.blood_type or '—',
                str(d.units_donated),
                d.donation_date.strftime('%d %b %Y') if d.donation_date else '—',
                f'{d.hemoglobin_level} g/dL' if d.hemoglobin_level else '—'
            ])
        story.append(tbl(don_rows, [5*cm, 2.5*cm, 2*cm, 4*cm, 4.5*cm]))
    else:
        story.append(Paragraph('No donations recorded yet.', ParagraphStyle('empty',
            fontSize=9, fontName='Helvetica', textColor=GRAY)))
    story.append(Spacer(1,12))

    # ══ 6. APPOINTMENTS ══════════════════════════════════════════════════════
    story.append(PB())
    story.append(sec('Appointments', 6))
    story.append(hr())
    story.append(note(f'{len(appts)} appointments total  ·  {sum(1 for a in appts if a.status=="completed")} completed  ·  {sum(1 for a in appts if a.status=="pending")} pending'))

    a_rows = [['Patient', 'Type', 'Date', 'Time', 'Blood Type', 'Status', 'Notes']]
    a_highlights = []
    for idx, a in enumerate(appts, 1):
        a_rows.append([
            f'{a.user.first_name} {a.user.last_name}',
            a.type.title(),
            a.appointment_date.strftime('%d %b %Y'),
            a.appointment_time or '—',
            a.blood_type_needed or (a.user.blood_type or '—'),
            a.status.title(),
            (a.admin_notes[:35]+'…') if a.admin_notes and len(a.admin_notes)>35 else (a.admin_notes or '—')
        ])
        if a.status == 'pending':   a_highlights.append((idx, WARN))
        elif a.status == 'rejected':a_highlights.append((idx, CRIT))
    story.append(tbl(a_rows, [3.8*cm, 1.8*cm, 2.8*cm, 1.8*cm, 2.2*cm, 2.2*cm, 4.4*cm], a_highlights))
    story.append(Spacer(1,12))

    # ══ 7. BLOOD REQUESTS ════════════════════════════════════════════════════
    story.append(PB())
    story.append(sec('Blood Requests', 7))
    story.append(hr())
    critical_count = sum(1 for r in reqs if r.urgency == 'critical')
    story.append(note(f'{len(reqs)} requests total  ·  {critical_count} critical  ·  {sum(1 for r in reqs if r.status=="fulfilled")} fulfilled'))

    req_rows = [['Patient', 'Blood Type', 'Units', 'Urgency', 'Reason', 'Date Requested', 'Status']]
    req_highlights = []
    for idx, r in enumerate(reqs, 1):
        req_rows.append([
            f'{r.requester.first_name} {r.requester.last_name}',
            r.blood_type,
            str(r.units_needed),
            r.urgency.title(),
            (r.reason[:35]+'…') if r.reason and len(r.reason)>35 else (r.reason or '—'),
            r.created_at.strftime('%d %b %Y'),
            r.status.title()
        ])
        if r.urgency == 'critical':    req_highlights.append((idx, CRIT))
        elif r.urgency == 'urgent':    req_highlights.append((idx, WARN))
        elif r.status == 'fulfilled':  req_highlights.append((idx, GREEN))
    story.append(tbl(req_rows, [3.5*cm, 2.2*cm, 1.8*cm, 2.2*cm, 4.5*cm, 3*cm, 2.8*cm], req_highlights))

    buf = build_pdf('Full System Report', facility.name, story, landscape_mode=True)
    resp = make_response(buf.read())
    resp.headers['Content-Type'] = 'application/pdf'
    resp.headers['Content-Disposition'] = f'attachment; filename=hemolink_full_report_{date.today()}.pdf'
    return resp


# ─── ADMIN CREATE ACCOUNT ─────────────────────────────────────────────────────

@app.route('/admin/create-account', methods=['GET', 'POST'])
@login_required
def admin_create_account():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        data = request.form
        email = data.get('email', '').strip().lower()
        if User.query.filter_by(email=email).first():
            return jsonify({'success': False, 'message': 'Email already registered.'})
        if data.get('national_id') and User.query.filter_by(national_id=data.get('national_id')).first():
            return jsonify({'success': False, 'message': 'National ID already registered.'})
        pw = bcrypt.generate_password_hash(data.get('password')).decode('utf-8')
        dob_str = data.get('date_of_birth')
        dob = datetime.strptime(dob_str, '%Y-%m-%d').date() if dob_str else None
        role = data.get('role', 'donor')
        # Admins created by admins need approval from another admin; others auto-approved
        needs_approval = False  # Admin-created accounts are approved by the creating admin's authority
        user = User(
            email=email, password=pw,
            first_name=data.get('first_name'), last_name=data.get('last_name'),
            phone=data.get('phone'), national_id=data.get('national_id'),
            role=role,
            facility_id=int(data.get('facility_id')) if data.get('facility_id') else current_user.facility_id,
            blood_type=data.get('blood_type'),
            date_of_birth=dob, gender=data.get('gender'),
            county=data.get('county'),
            is_approved=not needs_approval
        )
        db.session.add(user)
        db.session.commit()
        add_notification(user.id, f'Your {role} account has been created by {current_user.first_name} {current_user.last_name}. You can now log in.', 'success')
        msg = f'{role.title()} account created for {user.first_name} {user.last_name}. They can log in immediately.'
        return jsonify({'success': True, 'message': msg})
    facilities = Facility.query.all()
    return render_template('admin_create_account.html', facilities=facilities)


# ─── MEDICAL REPORTS ──────────────────────────────────────────────────────────

@app.route('/medical-reports', methods=['GET'])
@login_required
def medical_reports():
    if current_user.role == 'admin':
        reports = MedicalReport.query.filter_by(facility_id=current_user.facility_id) \
            .order_by(MedicalReport.created_at.desc()).all()
        users = User.query.filter_by(facility_id=current_user.facility_id, is_approved=True) \
            .filter(User.role != 'admin').order_by(User.last_name).all()
    else:
        reports = MedicalReport.query.filter_by(user_id=current_user.id) \
            .order_by(MedicalReport.created_at.desc()).all()
        users = []
    return render_template('medical_reports.html', reports=reports, users=users)

@app.route('/medical-reports/submit', methods=['POST'])
@login_required
def submit_medical_report():
    data = request.form
    # Admin can submit on behalf of a member; member submits for themselves
    if current_user.role == 'admin':
        user_id = int(data.get('user_id', current_user.id))
    else:
        user_id = current_user.id
    report = MedicalReport(
        user_id=user_id,
        facility_id=current_user.facility_id,
        title=data.get('title', '').strip() or 'Medical Report',
        report_type=data.get('report_type', 'general'),
        content=data.get('content', '').strip(),
        blood_pressure=data.get('blood_pressure', '').strip() or None,
        hemoglobin=float(data.get('hemoglobin')) if data.get('hemoglobin') else None,
        weight_kg=float(data.get('weight_kg')) if data.get('weight_kg') else None,
        temperature=float(data.get('temperature')) if data.get('temperature') else None,
        pulse=int(data.get('pulse')) if data.get('pulse') else None,
        notes=data.get('notes', '').strip() or None,
        submitted_by=current_user.id,
    )
    db.session.add(report)
    db.session.commit()
    # Notify admin if member submitted
    if current_user.role != 'admin':
        admins = User.query.filter_by(facility_id=current_user.facility_id, role='admin').all()
        for a in admins:
            add_notification(a.id, f'New medical report from {current_user.first_name} {current_user.last_name}: {report.title}', 'info')
    return jsonify({'success': True, 'message': 'Medical report submitted successfully.'})

@app.route('/medical-reports/<int:rid>')
@login_required
def view_medical_report(rid):
    report = MedicalReport.query.get_or_404(rid)
    if current_user.role != 'admin' and report.user_id != current_user.id:
        return jsonify({'error': 'Access denied'}), 403
    return jsonify({
        'id': report.id,
        'title': report.title,
        'report_type': report.report_type.replace('_',' ').title(),
        'content': report.content,
        'blood_pressure': report.blood_pressure,
        'hemoglobin': report.hemoglobin,
        'weight_kg': report.weight_kg,
        'temperature': report.temperature,
        'pulse': report.pulse,
        'notes': report.notes,
        'created_at': report.created_at.strftime('%d %b %Y %H:%M'),
        'patient': f'{report.user.first_name} {report.user.last_name}' if report.user else '—',
        'submitted_by': f'{report.submitter.first_name} {report.submitter.last_name}' if report.submitter else '—',
    })

@app.route('/medical-reports/<int:rid>/delete', methods=['POST'])
@login_required
def delete_medical_report(rid):
    report = MedicalReport.query.get_or_404(rid)
    if current_user.role != 'admin' and report.user_id != current_user.id:
        return jsonify({'success': False, 'message': 'Access denied'})
    db.session.delete(report)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Report deleted.'})



@app.route('/medical-reports/<int:rid>/pdf')
@login_required
def medical_report_pdf(rid):
    report = MedicalReport.query.get_or_404(rid)
    if current_user.role != 'admin' and report.user_id != current_user.id:
        return jsonify({'error': 'Access denied'}), 403
    
    from io import BytesIO
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        topMargin=2*cm, bottomMargin=2*cm, leftMargin=2*cm, rightMargin=2*cm)
    
    RED = colors.HexColor('#C8102E')
    DARK = colors.HexColor('#1a1a1a')
    GRAY = colors.HexColor('#888888')
    
    story = []
    
    # Header
    story.append(Paragraph('HemoLink Kenya', ParagraphStyle('hdr',
        fontSize=20, fontName='Helvetica-Bold', textColor=RED, alignment=TA_CENTER, spaceAfter=4)))
    story.append(Paragraph('Medical Report', ParagraphStyle('sub',
        fontSize=12, fontName='Helvetica', textColor=DARK, alignment=TA_CENTER, spaceAfter=2)))
    story.append(HRFlowable(width='100%', thickness=1, color=RED, spaceAfter=14))
    
    # Meta
    patient = report.user
    facility = Facility.query.get(report.facility_id)
    meta_rows = [
        ['Report Title', report.title],
        ['Report Type', report.report_type.replace('_',' ').title()],
        ['Patient', f'{patient.first_name} {patient.last_name}' if patient else '—'],
        ['Facility', facility.name if facility else '—'],
        ['Date', report.created_at.strftime('%d %B %Y %H:%M')],
        ['Submitted By', f'{report.submitter.first_name} {report.submitter.last_name}' if report.submitter else '—'],
    ]
    t = Table(meta_rows, colWidths=[4.5*cm, 11.5*cm])
    t.setStyle(TableStyle([
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME', (1,0), (1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('TEXTCOLOR', (0,0), (0,-1), GRAY),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, colors.HexColor('#f9f9f9')]),
        ('GRID', (0,0), (-1,-1), 0.3, colors.HexColor('#e0e0e0')),
    ]))
    story += [t, Spacer(1, 14)]
    
    # Vitals
    vitals = []
    if report.blood_pressure: vitals.append(['Blood Pressure', report.blood_pressure])
    if report.hemoglobin:     vitals.append(['Haemoglobin', f'{report.hemoglobin} g/dL'])
    if report.temperature:    vitals.append(['Temperature', f'{report.temperature} °C'])
    if report.pulse:          vitals.append(['Pulse', f'{report.pulse} bpm'])
    if report.weight_kg:      vitals.append(['Weight', f'{report.weight_kg} kg'])
    if vitals:
        story.append(Paragraph('Vitals', ParagraphStyle('sec',
            fontSize=11, fontName='Helvetica-Bold', textColor=RED, spaceAfter=6, spaceBefore=4)))
        vt = Table(vitals, colWidths=[4.5*cm, 11.5*cm])
        vt.setStyle(TableStyle([
            ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
            ('FONTNAME', (1,0), (1,-1), 'Helvetica'),
            ('FONTSIZE', (0,0), (-1,-1), 10),
            ('TEXTCOLOR', (0,0), (0,-1), GRAY),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('GRID', (0,0), (-1,-1), 0.3, colors.HexColor('#e0e0e0')),
        ]))
        story += [vt, Spacer(1, 14)]
    
    # Clinical summary
    story.append(Paragraph('Clinical Summary', ParagraphStyle('sec',
        fontSize=11, fontName='Helvetica-Bold', textColor=RED, spaceAfter=6)))
    story.append(Paragraph(report.content.replace('\n', '<br/>').replace('\r',''),
        ParagraphStyle('body', fontSize=10, fontName='Helvetica', leading=15, spaceAfter=10)))
    
    # Notes
    if report.notes:
        story.append(Paragraph('Additional Notes', ParagraphStyle('sec',
            fontSize=11, fontName='Helvetica-Bold', textColor=RED, spaceAfter=6, spaceBefore=4)))
        story.append(Paragraph(report.notes.replace('\n', '<br/>').replace('\r',''),
            ParagraphStyle('notes', fontSize=10, fontName='Helvetica', textColor=GRAY, leading=15)))
    
    # Footer
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#dddddd'), spaceAfter=6))
    story.append(Paragraph(f'HemoLink Kenya · {facility.name if facility else ""} · Confidential Medical Record',
        ParagraphStyle('ft', fontSize=8, fontName='Helvetica', textColor=GRAY, alignment=TA_CENTER)))
    
    doc.build(story)
    buf.seek(0)
    
    response = make_response(buf.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename=medical_report_{report.id}_{date.today()}.pdf'
    return response

# ─── FACILITY MANAGEMENT ──────────────────────────────────────────────────────

@app.route('/admin/facilities/add', methods=['POST'])
@login_required
def add_facility():
    if current_user.role != 'admin':
        return jsonify({'success': False, 'message': 'Access denied'})
    data = request.form
    name = data.get('name', '').strip()
    county = data.get('county', '').strip()
    if not name or not county:
        return jsonify({'success': False, 'message': 'Facility name and county are required.'})
    if Facility.query.filter_by(name=name).first():
        return jsonify({'success': False, 'message': 'A facility with this name already exists.'})
    try:
        lat = float(data.get('latitude')) if data.get('latitude') else None
        lng = float(data.get('longitude')) if data.get('longitude') else None
    except (ValueError, TypeError):
        lat = lng = None
    f = Facility(
        name=name, county=county,
        address=data.get('address', '').strip() or None,
        phone=data.get('phone', '').strip() or None,
        email=data.get('email', '').strip() or None,
        latitude=lat, longitude=lng
    )
    db.session.add(f)
    db.session.commit()
    return jsonify({'success': True, 'message': f'Facility "{name}" added successfully.', 'id': f.id})

# ─── FACILITY MAP ─────────────────────────────────────────────────────────────

@app.route('/facilities/map')
@login_required
def facilities_map():
    facilities = Facility.query.all()
    facility_data = []
    for f in facilities:
        inv = BloodInventory.query.filter_by(facility_id=f.id).all()
        total_units = sum(i.units_available for i in inv)
        blood_summary = {i.blood_type: i.units_available for i in inv}
        donor_count = User.query.filter_by(facility_id=f.id, role='donor', is_approved=True).count()
        facility_data.append({
            'id': f.id,
            'name': f.name,
            'county': f.county,
            'address': f.address,
            'phone': f.phone,
            'email': f.email,
            'lat': f.latitude,
            'lng': f.longitude,
            'total_units': total_units,
            'donor_count': donor_count,
            'blood_summary': blood_summary,
            'is_own': f.id == current_user.facility_id
        })
    return render_template('facilities_map.html', facilities=json.dumps(facility_data))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_database()
    app.run(debug=True, host='0.0.0.0', port=5000)

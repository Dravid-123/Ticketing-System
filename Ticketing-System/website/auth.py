from flask import Blueprint, render_template, request, flash, redirect, url_for
from .models import User, Notification
from werkzeug.security import generate_password_hash, check_password_hash
from . import db
from flask_login import login_user, login_required, logout_user, current_user


auth = Blueprint('auth', __name__)

# -------- Password Reset (via Employee ID & first name) --------
@auth.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        employee_id = (request.form.get('employee_id') or '').strip()
        first_name = (request.form.get('first_name') or '').strip()
        security_question = request.form.get('security_question')
        security_answer = (request.form.get('security_answer') or '').strip()
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        # Basic validations
        if not employee_id or not first_name:
            flash('Employee ID and First Name are required.', category='error')
            return redirect(url_for('views.home') + '#login')
        if not new_password or not confirm_password:
            flash('Please enter and confirm your new password.', category='error')
            return redirect(url_for('views.home') + '#login')
        if new_password != confirm_password:
            flash("Passwords don't match.", category='error')
            return redirect(url_for('views.home') + '#login')
        if len(new_password) < 7:
            flash('Password must be at least 7 characters.', category='error')
            return redirect(url_for('views.home') + '#login')

        user = User.query.filter_by(employee_id=employee_id, first_name=first_name).first()
        if not user:
            flash('No matching account found. Please verify details.', category='error')
            return redirect(url_for('views.home') + '#login')

        # Verify security question and answer
        if user.security_question != security_question or not check_password_hash(user.security_answer, security_answer):
            flash('Security question or answer is incorrect.', category='error')
            return redirect(url_for('views.home') + '#login')

        # Update password
        user.password = generate_password_hash(new_password, method='sha256')
        db.session.commit()

        flash('Password updated successfully. Please login with your new password.', category='success')
        return redirect(url_for('views.home') + '#login')

    # GET renders a simple reset form in the home page content
    return redirect(url_for('views.home') + '#login')


# User
@auth.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Login using only employee_id + password for both users and admins
        employee_id = (request.form.get('employee_id') or '').strip()
        password = request.form.get('password')

        user = User.query.filter_by(employee_id=employee_id).first() if employee_id else None

        if user:
            if check_password_hash(user.password, password):
                flash('Logged in successfully!', category='success')
                login_user(user, remember=True)
                if user.accountType == "admin":
                    # Ensure admin has a valid admin_code
                    if user.admin_code not in ("1234", "1235", "1236"):
                        flash('Your admin account is missing a valid admin code. Please contact support.', category='error')
                        return redirect(url_for('auth.login'))
                    return redirect(url_for('views.adminDashboard', user=current_user))

                return redirect(url_for('views.tickets', user=current_user))
            else:
                flash('Incorrect password, try again.', category='error')
        else:
            flash('Account not found. Check your Employee ID or Sign Up first.', category='error')

    return redirect(url_for('views.home') + '#login')


@auth.route('/sign-up', methods=['GET', 'POST'])
def sign_up():
    if request.method == 'POST':
        # User signup with employee_id + password only (no email required)
        employee_id = (request.form.get('employee_id') or '').strip()
        first_name = (request.form.get('firstName') or '').strip()
        last_name = (request.form.get('lastName') or '').strip()
        password1 = request.form.get('password1')
        password2 = request.form.get('password2')
        security_question = request.form.get('security_question')
        security_answer = (request.form.get('security_answer') or '').strip()

        existing_emp = User.query.filter_by(employee_id=employee_id).first() if employee_id else None
        name = User.query.filter_by(first_name=first_name).first() if first_name else None

        if not employee_id:
            flash('Employee ID is required.', category='error')
        elif existing_emp:
            flash('Employee ID already exists.', category='error')
        elif name:
            flash('Username already exists.', category='error')
        elif len(first_name) < 3:
            flash('First name must be greater than 2 characters.', category='error')
        elif len(first_name) > 30:
            flash('First name must be less than 30 characters.', category='error')
        elif password1 != password2:
            flash('Passwords don\'t match.', category='error')
        elif len(password1) < 7:
            flash('Password must be at least 7 characters.', category='error')
        elif not security_question or not security_answer:
            flash('Security question and answer are required.', category='error')
        else:
            new_user = User(
                email=None,
                employee_id=employee_id,
                first_name=first_name,
                last_name=last_name,
                password=generate_password_hash(password1, method='sha256'),
                accountType="user",
                security_question=security_question,
                security_answer=generate_password_hash(security_answer, method='sha256')
            )
            db.session.add(new_user)
            db.session.commit()
            login_user(new_user, remember=True)
            flash('Account created!', category='success')
            # Notification
            new_notification = Notification(
                message=f"Account Created. Welcome {first_name}!", status="success", user_id=current_user.id)
            db.session.add(new_notification)
            db.session.commit()
            return redirect(url_for('views.tickets'))

    return redirect(url_for('views.home') + '#signup')


@auth.route('/admin-signup', methods=['GET', 'POST'])
def admin_signup():
    if request.method == 'POST':
        employee_id = (request.form.get('employee_id') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        first_name = (request.form.get('firstName') or '').strip()
        last_name = (request.form.get('lastName') or '').strip()
        password1 = request.form.get('password1')
        password2 = request.form.get('password2')
        # Support both legacy 'secretcode' and new 'admin_code' field names
        secretcode = (request.form.get('admin_code') or request.form.get('secretcode') or '').strip()
        security_question = request.form.get('security_question')
        security_answer = (request.form.get('security_answer') or '').strip()

        existing_emp = User.query.filter_by(employee_id=employee_id).first() if employee_id else None
        user = User.query.filter_by(email=email).first() if email else None
        name = User.query.filter_by(first_name=first_name).first() if first_name else None

        # Validate admin code
        if secretcode not in ("1234", "1235", "1236"):
            flash('Incorrect Admin Code! Choose a valid admin code.', category='error')
        elif not employee_id:
            flash('Employee ID is required for admin accounts.', category='error')
        elif existing_emp:
            flash('Employee ID already exists.', category='error')
        elif not email:
            flash('Email is required for admin accounts.', category='error')
        elif user:
            flash('Email already exists.', category='error')
        elif name:
            flash('Username already exists.', category='error')
        elif len(first_name) < 3:
            flash('First name must be greater than 2 characters.', category='error')
        elif len(first_name) > 30:
            flash('First name must be less than 30 characters.', category='error')
        elif password1 != password2:
            flash('Passwords don\'t match.', category='error')
        elif len(password1) < 7:
            flash('Password must be at least 7 characters.', category='error')
        elif not security_question or not security_answer:
            flash('Security question and answer are required.', category='error')
        else:
            if secretcode == '1236':
                admin_role = 'Super Admin'
            elif secretcode == '1234':
                admin_role = 'IT Admin'
            else:
                admin_role = 'Hardware Admin'
            new_user = User(
                email=email,
                employee_id=employee_id,
                first_name=first_name,
                last_name=last_name,
                password=generate_password_hash(password1, method='sha256'),
                accountType="admin",
                admin_code=secretcode,
                admin_role=admin_role,
                security_question=security_question,
                security_answer=generate_password_hash(security_answer, method='sha256')
            )
            db.session.add(new_user)
            db.session.commit()
            login_user(new_user, remember=True)
            flash(f'Account created as {admin_role}!', category='success')
            # Notification
            new_notification = Notification(
                message=f"Admin Account Created. Welcome {admin_role} {first_name}!", status="success", user_id=current_user.id)
            db.session.add(new_notification)
            db.session.commit()
            return redirect(url_for('views.adminDashboard', user=current_user))

    return redirect(url_for('views.home') + '#admin')


@auth.route('/logout')
@login_required
def logout():
    
    logout_user()
    flash('Logged Out!', category='success')
    return redirect(url_for('views.home'))

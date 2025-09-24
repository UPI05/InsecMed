from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, make_response
import requests

app = Flask(__name__)
app.secret_key = 'xxx'  # Dùng cho flash messages
API_HOST = 'http://10.102.196.113:8080'  # API server

# ---------------- Routes ----------------

@app.route('/')
def index():
    return render_template('login.html')

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/diagnose')
def diagnosis():
    return render_template('diagnosis.html', api_host=API_HOST)

@app.route('/vision-qa')
def vision_qa():
    return render_template('vision_qa.html', api_host=API_HOST)

@app.route('/pending-cases')
def pending_cases():
    return render_template('pending_cases.html', api_host=API_HOST)

@app.route('/history')
def history():
    try:
        response = requests.get(f"{API_HOST}/getStat", cookies={'session': request.cookies.get('session')})
        data = response.json() if response.status_code == 200 else {}
    except requests.RequestException:
        data = {}
        flash('Lỗi kết nối API.', 'danger')
    
    return render_template('history.html',
                           diagnoses=data.get('diagnoses', []),
                           qa_interactions=data.get('qa_interactions', []),
                           stats=data.get('stats', {}))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        files = {'profile_pic': request.files.get('profile_pic')}
        try:
            response = requests.post(f"{API_HOST}/register", data=request.form, files=files)
            flash(response.json().get('message') or response.json().get('error'), 
                  'success' if response.status_code == 201 else 'danger')
            if response.status_code == 201:
                return redirect(url_for('index'))
        except requests.RequestException as e:
            flash(f'Lỗi kết nối API: {e}', 'danger')
        return redirect(url_for('register'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            response = requests.post(f"{API_HOST}/login", data=request.form)
            if response.status_code == 200:
                # Forward cookie từ server.py về trình duyệt
                resp = make_response(redirect(url_for('pending_cases')))
                if 'session' in response.cookies:
                    resp.set_cookie('session', response.cookies['session'])
                flash(response.json().get('message'), 'success')
                return resp
            else:
                flash(response.json().get('error'), 'danger')
        except requests.RequestException as e:
            flash(f'Lỗi kết nối API: {e}', 'danger')
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if request.method == 'POST':
        files = {'profile_pic': request.files.get('profile_pic')}
        try:
            response = requests.post(f"{API_HOST}/profile", data=request.form, files=files,
                                     cookies={'session': request.cookies.get('session')})
            flash(response.json().get('message') or response.json().get('error'),
                  'success' if response.status_code == 200 else 'danger')
        except requests.RequestException as e:
            flash(f'Lỗi kết nối API: {e}', 'danger')
        return redirect(url_for('profile'))

    try:
        response = requests.get(f"{API_HOST}/profile", cookies={'session': request.cookies.get('session')})
        user = response.json() if response.status_code == 200 else {}
    except requests.RequestException:
        user = {}
        flash('Lỗi kết nối API.', 'danger')
    return render_template('profile.html', user=user)

@app.route('/logout')
def logout():
    try:
        requests.post(f"{API_HOST}/logout", cookies={'session': request.cookies.get('session')})
    except requests.RequestException:
        pass
    # Xóa cookie session ở trình duyệt
    resp = make_response(redirect(url_for('index')))
    resp.delete_cookie('session')
    flash('Đã đăng xuất.', 'success')
    return resp

# ------------- API Proxy ----------------

@app.route('/diagnose', methods=['POST'])
def diagnose():
    files = {'file': request.files.get('file')}
    try:
        response = requests.post(f"{API_HOST}/diagnose", data=request.form, files=files,
                                 cookies={'session': request.cookies.get('session')})
        return jsonify(response.json()), response.status_code
    except requests.RequestException as e:
        return jsonify({"error": f"Lỗi kết nối API: {e}"}), 500

@app.route('/vqa-diagnose', methods=['POST'])
def vqa_diagnose():
    files = {'file': request.files.get('file')}
    try:
        response = requests.post(f"{API_HOST}/vqa-diagnose", data=request.form, files=files,
                                 cookies={'session': request.cookies.get('session')})
        return jsonify(response.json()), response.status_code
    except requests.RequestException as e:
        return jsonify({"error": f"Lỗi kết nối API: {e}"}), 500

# ---------------- Main ----------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

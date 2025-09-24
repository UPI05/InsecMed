from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
import requests

app = Flask(__name__)
app.secret_key = ''  # Replace with a strong secret
API_HOST = 'http://10.102.196.113:8080' # API server

# ---------------- Routes ----------------

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('history'))
    return render_template('login.html')

@app.route('/terms')
def terms():
    return render_template('terms.html')  # hoặc nội dung nào bạn muốn

@app.route('/diagnose')
def diagnosis():
    if 'user_id' not in session:
        flash('Vui lòng đăng nhập để sử dụng chức năng chẩn đoán.', 'warning')
        return redirect(url_for('index'))
    return render_template('diagnosis.html', api_host=API_HOST)

@app.route('/vision-qa')
def vision_qa():
    if 'user_id' not in session:
        flash('Vui lòng đăng nhập để sử dụng chức năng Q&A.', 'warning')
        return redirect(url_for('index'))
    return render_template('vision_qa.html', api_host=API_HOST)

@app.route('/history')
def history():
    if 'user_id' not in session:
        flash('Vui lòng đăng nhập để xem lịch sử.', 'warning')
        return redirect(url_for('index'))
    
    try:
        response = requests.get(f"{API_HOST}/history", cookies={'session': request.cookies.get('session')})
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
                session['user_id'] = response.cookies.get('session')
                flash(response.json().get('message'), 'success')
                return redirect(url_for('history'))
            else:
                flash(response.json().get('error'), 'danger')
        except requests.RequestException as e:
            flash(f'Lỗi kết nối API: {e}', 'danger')
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        flash('Vui lòng đăng nhập.', 'warning')
        return redirect(url_for('index'))
    
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
    session.pop('user_id', None)
    flash('Đã đăng xuất.', 'success')
    return redirect(url_for('index'))

# ------------- API Proxy ----------------

@app.route('/diagnose', methods=['POST'])
def diagnose():
    if 'user_id' not in session:
        return jsonify({"error": "Vui lòng đăng nhập."}), 401
    files = {'file': request.files.get('file')}
    try:
        response = requests.post(f"{API_HOST}/diagnose", data=request.form, files=files,
                                 cookies={'session': request.cookies.get('session')})
        return jsonify(response.json()), response.status_code
    except requests.RequestException as e:
        return jsonify({"error": f"Lỗi kết nối API: {e}"}), 500

@app.route('/vqa-diagnose', methods=['POST'])
def vqa_diagnose():
    if 'user_id' not in session:
        return jsonify({"error": "Vui lòng đăng nhập."}), 401
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

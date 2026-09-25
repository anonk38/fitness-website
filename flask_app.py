from flask import Flask, request, jsonify, send_file, session, make_response, render_template_string, redirect
from datetime import timedelta, datetime
import sqlite3
import json
import os
import hashlib

app = Flask(__name__)

# ১০ বছরের স্থায়ী সেশন
app.secret_key = 'fitpulse_lifetime_permanent_secret_key_2026_fixed'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=3650)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'physique.db')
HTML_FILE = os.path.join(BASE_DIR, 'index.html')

# অ্যাডমিন রিকভারির জন্য মাস্টার সিক্রেট কী
ADMIN_RECOVERY_MASTER_KEY = "administer78"

# 🇧🇩 বাংলাদেশ টাইম (BST = UTC + 6 Hours) ক্যালকুলেটর ফাংশন (100% Reliable for PythonAnywhere)
def get_bd_time_str():
    bd_time = datetime.utcnow() + timedelta(hours=6)
    return bd_time.strftime("%Y-%m-%d %I:%M %p")

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def init_db():
    try:
        os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password TEXT NOT NULL,
                profile TEXT NOT NULL,
                customFoodDB TEXT NOT NULL,
                history TEXT NOT NULL
            )
        ''')

        # 📍 Location & Altitude এর কলাম চেক ও এড করা
        try:
            c.execute('ALTER TABLE users ADD COLUMN latitude REAL')
        except sqlite3.OperationalError: pass
        try:
            c.execute('ALTER TABLE users ADD COLUMN longitude REAL')
        except sqlite3.OperationalError: pass
        try:
            c.execute('ALTER TABLE users ADD COLUMN altitude REAL')
        except sqlite3.OperationalError: pass
        try:
            c.execute('ALTER TABLE users ADD COLUMN last_location_update TEXT')
        except sqlite3.OperationalError: pass

        c.execute('''
            CREATE TABLE IF NOT EXISTS admin_config (
                key TEXT PRIMARY KEY,
                val TEXT NOT NULL
            )
        ''')
        # ডিফল্ট অ্যাডমিন পাসওয়ার্ড (1234) সেট করা যদি আগে না থাকে
        c.execute('SELECT * FROM admin_config WHERE key = ?', ('admin_pass',))
        if not c.fetchone():
            c.execute('INSERT INTO admin_config (key, val) VALUES (?, ?)', ('admin_pass', hash_password('1234')))
        conn.commit()
        conn.close()
    except Exception as e:
        print("DB Init Error:", e)

init_db()

def get_db_connection():
    init_db()
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def get_admin_pass_hash():
    conn = get_db_connection()
    c = conn.cursor()
    row = c.execute('SELECT val FROM admin_config WHERE key = ?', ('admin_pass',)).fetchone()
    conn.close()
    return row['val'] if row else hash_password('1234')

@app.route('/')
def home():
    return send_file(HTML_FILE, mimetype='text/html')

@app.route('/manifest.json')
def manifest():
    manifest_data = {
        "name": "FitPulse - Pro Edition",
        "short_name": "FitPulse",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0b0f0c",
        "theme_color": "#84cc16",
        "icons": [{"src": "https://cdn-icons-png.flaticon.com/512/2964/2964514.png", "sizes": "512x512", "type": "image/png"}]
    }
    response = make_response(jsonify(manifest_data))
    response.headers["Content-Type"] = "application/manifest+json"
    return response

@app.route('/sw.js')
def service_worker():
    sw_code = "self.addEventListener('install', (e) => self.skipWaiting()); self.addEventListener('fetch', (e) => {});"
    response = make_response(sw_code)
    response.headers["Content-Type"] = "application/javascript"
    return response

@app.route('/api/auth/register', methods=['POST'])
def register():
    try:
        data = request.get_json(force=True) or {}
        username = str(data.get('username', '')).strip().lower()
        password = str(data.get('password', '')).strip()

        if not username or not password:
            return jsonify({"status": "error", "message": "Username/password empty!"}), 400

        conn = get_db_connection()
        c = conn.cursor()
        user = c.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

        if user:
            conn.close()
            return jsonify({"status": "error", "message": "Username taken!"}), 400

        default_profile = json.dumps({"targetCal": 1700, "targetProtein": 120, "targetSugar": 36, "setupComplete": False, "appLang": "bn", "deletedDefaultFoodIds": []}, ensure_ascii=False)
        default_foods = json.dumps([], ensure_ascii=False)
        default_history = json.dumps({}, ensure_ascii=False)

        c.execute('''
            INSERT INTO users (username, password, profile, customFoodDB, history)
            VALUES (?, ?, ?, ?, ?)
        ''', (username, hash_password(password), default_profile, default_foods, default_history))
        conn.commit()
        conn.close()

        session.permanent = True
        session['username'] = username

        return jsonify({
            "status": "success",
            "username": username,
            "data": {
                "profile": json.loads(default_profile),
                "customFoodDB": [],
                "history": {}
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    try:
        data = request.get_json(force=True) or {}
        username = str(data.get('username', '')).strip().lower()
        password = str(data.get('password', '')).strip()

        conn = get_db_connection()
        c = conn.cursor()
        user = c.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

        if user and user['password'] == hash_password(password):
            session.permanent = True
            session['username'] = username

            raw_foods = json.loads(user['customFoodDB']) if user['customFoodDB'] else []
            profile = json.loads(user['profile'])
            history = json.loads(user['history'])
            conn.close()

            return jsonify({
                "status": "success",
                "username": username,
                "data": {
                    "profile": profile,
                    "customFoodDB": raw_foods,
                    "history": history
                }
            })

        conn.close()
        return jsonify({"status": "error", "message": "Invalid username or password!"}), 401
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.pop('username', None)
    session.pop('is_admin_portal', None)
    return jsonify({"status": "success"})

@app.route('/api/auth/reset-password', methods=['POST'])
def reset_password():
    try:
        data = request.get_json(force=True) or {}
        username = str(data.get('username', '')).strip().lower()
        new_password = str(data.get('new_password', '')).strip()

        if not username or not new_password:
            return jsonify({"status": "error", "message": "Username and new password required!"}), 400

        conn = get_db_connection()
        c = conn.cursor()
        user = c.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

        if not user:
            conn.close()
            return jsonify({"status": "error", "message": "Username not found!"}), 404

        c.execute('UPDATE users SET password = ? WHERE username = ?', (hash_password(new_password), username))
        conn.commit()
        conn.close()

        return jsonify({"status": "success", "message": "Password updated successfully!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/delete-account', methods=['POST'])
def delete_account():
    if 'username' not in session:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    try:
        username = session['username']
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('DELETE FROM users WHERE username = ?', (username,))
        conn.commit()
        conn.close()

        session.pop('username', None)
        return jsonify({"status": "success", "message": "Account deleted forever!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/get-data', methods=['GET'])
def get_data():
    if 'username' not in session:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    try:
        conn = get_db_connection()
        c = conn.cursor()
        user = c.execute('SELECT * FROM users WHERE username = ?', (session['username'],)).fetchone()

        if not user:
            conn.close()
            return jsonify({"status": "error", "message": "User not found"}), 404

        raw_foods = json.loads(user['customFoodDB']) if user['customFoodDB'] else []
        profile = json.loads(user['profile'])
        history = json.loads(user['history'])
        conn.close()

        return jsonify({
            "status": "success",
            "username": session['username'],
            "data": {
                "profile": profile,
                "customFoodDB": raw_foods,
                "history": history
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/save-data', methods=['POST'])
def update_data():
    if 'username' not in session:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    try:
        new_user_data = request.get_json(force=True) or {}
        username = session['username']

        profile_json = json.dumps(new_user_data.get("profile", {}), ensure_ascii=False)
        history_json = json.dumps(new_user_data.get("history", {}), ensure_ascii=False)
        custom_food_json = json.dumps(new_user_data.get("customFoodDB", []), ensure_ascii=False)

        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''
            UPDATE users
            SET profile = ?, history = ?, customFoodDB = ?
            WHERE username = ?
        ''', (profile_json, history_json, custom_food_json, username))
        conn.commit()
        conn.close()

        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# 📍 লাইভ লোকেশন সিঙ্ক এন্ডপয়েন্ট (বাংলাদেশ লোকাল টাইমসহ)
@app.route('/api/sync-location', methods=['POST'])
def sync_location():
    if 'username' not in session:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    try:
        data = request.get_json(force=True) or {}
        lat = data.get('latitude')
        lng = data.get('longitude')
        alt = data.get('altitude')

        if lat is not None and lng is not None:
            bd_time_now = get_bd_time_str()
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('''
                UPDATE users
                SET latitude = ?, longitude = ?, altitude = ?, last_location_update = ?
                WHERE username = ?
            ''', (lat, lng, alt, bd_time_now, session['username']))
            conn.commit()
            conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ================= 🛡️ অ্যাডমিন প্যানেল ভিউ ও কন্ট্রোল =================
ADMIN_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FitPulse Admin Dashboard</title>
<style>
:root { --bg: #0b0f0c; --card: rgba(22, 27, 24, 0.85); --primary: #84cc16; --text: #e2e8f0; --danger: #ef4444; --border: rgba(132, 204, 22, 0.25); --input-bg: rgba(0,0,0,0.5); }
* { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
body { background: var(--bg); color: var(--text); padding: 25px 15px; min-height: 100vh; }
.container { max-width: 1250px; margin: 0 auto; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 25px; padding-bottom: 15px; border-bottom: 1px solid var(--border); flex-wrap: wrap; gap: 10px; }
.title { font-size: 1.6rem; font-weight: 800; color: var(--primary); }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 25px; }
.stat-card { background: var(--card); border: 1px solid var(--border); padding: 20px; border-radius: 16px; text-align: center; }
.stat-val { font-size: 2.2rem; font-weight: 800; color: var(--primary); margin-top: 5px; }
table { width: 100%; border-collapse: collapse; background: var(--card); border-radius: 16px; overflow: hidden; border: 1px solid var(--border); }
th, td { padding: 14px 16px; text-align: left; border-bottom: 1px solid var(--border); font-size: 0.88rem; vertical-align: middle; }
th { background: rgba(132, 204, 22, 0.12); color: var(--primary); font-weight: 700; }
.btn-action { padding: 6px 12px; border-radius: 8px; cursor: pointer; font-size: 0.8rem; font-weight: bold; margin-bottom: 4px; display: inline-block; }
.btn-edit { background: rgba(132, 204, 22, 0.15); color: var(--primary); border: 1px solid var(--primary); }
.btn-reset { background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid #38bdf8; }
.btn-del { background: rgba(239, 68, 68, 0.15); color: var(--danger); border: 1px solid var(--danger); }
.btn-location { background: rgba(132, 204, 22, 0.15); color: var(--primary); border: 1px solid var(--primary); text-decoration: none; padding: 7px 12px; border-radius: 8px; display: inline-block; font-size: 0.82rem; font-weight: bold; transition: 0.2s; }
.btn-location:hover { background: var(--primary); color: #000; }
.btn-primary { background: var(--primary); color: #000; border: none; padding: 9px 16px; border-radius: 10px; cursor: pointer; font-weight: bold; }
.btn-logout { background: var(--border); color: var(--text); border: none; padding: 8px 16px; border-radius: 8px; cursor: pointer; font-weight: bold; }
.pass-hash { font-family: monospace; font-size: 0.72rem; color: #94a3b8; max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Modal Styles */
.modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.85); backdrop-filter: blur(8px); align-items: center; justify-content: center; z-index: 100; padding: 20px; }
.modal-content { background: #161b18; border: 1px solid var(--border); border-radius: 20px; width: 100%; max-width: 440px; padding: 25px; max-height: 90vh; overflow-y: auto; }
.modal-title { font-size: 1.2rem; font-weight: bold; color: var(--primary); margin-bottom: 15px; }
input, select { width: 100%; padding: 11px; margin-bottom: 12px; background: var(--input-bg); border: 1px solid var(--border); border-radius: 10px; color: #fff; outline: none; }
label { font-size: 0.8rem; color: #94a3b8; display: block; margin-bottom: 4px; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div>
      <div class="title">⚡ FitPulse Super-Admin Panel</div>
      <div style="font-size: 0.85rem; color: #94a3b8; margin-top: 4px;">রিয়েলটাইম ইউজার ডাটাবেজ ও লাইভ লোকেশন মনিটরিং</div>
    </div>
    <div style="display: flex; gap: 8px;">
      <button class="btn-primary" onclick="openAdminPassModal()">🔐 Change Admin Password</button>
      <form action="/admin/logout" method="POST" style="margin:0;"><button class="btn-logout">Logout</button></form>
    </div>
  </div>

  <div class="stat-grid">
    <div class="stat-card">
      <div style="color: #94a3b8; font-size: 0.85rem;">মোট নিবন্ধিত ইউজার</div>
      <div class="stat-val">{{ users|length }}</div>
    </div>
  </div>

  <div style="overflow-x: auto;">
    <table>
      <thead>
        <tr>
          <th>ইউজারনেম</th>
          <th>পাসওয়ার্ড (Hash)</th>
          <th>প্রোফাইল বিবরণ</th>
          <th>ওজন ও লক্ষ্য</th>
          <th>লাইভ লোকেশন (GPS)</th>
          <th>অ্যাকশন</th>
        </tr>
      </thead>
      <tbody>
        {% for u in users %}
        {% set prof = u.profile_data %}
        <tr>
          <td><b style="color: var(--primary); font-size: 1rem;">{{ u.username }}</b><br><small style="color:#94a3b8;">{{ u.history_days }} দিনের ডাটা</small></td>
          <td><div class="pass-hash" title="{{ u.password }}">{{ u.password }}</div></td>
          <td>
            <div style="line-height: 1.45;">
              <b>{{ prof.gender or '-' }}</b> | <b>{{ prof.age or '-' }} yrs</b><br>
              উচ্চতা: {{ prof.heightFeet or 0 }} ft {{ prof.heightInches or 0 }} in<br>
              DOB: {{ prof.dob or '-' }}
            </div>
          </td>
          <td>
            <div style="line-height: 1.45;">
              বর্তমান: <b style="color:#f59e0b">{{ prof.lastWeight or '-' }} kg</b><br>
              টার্গেট: <b style="color:#38bdf8">{{ prof.targetWeight or '-' }} kg</b><br>
              ক্যালোরি: {{ prof.targetCal or '-' }} kcal
            </div>
          </td>
          <td>
            {% if u.latitude and u.longitude %}
              <a href="https://www.google.com/maps?q={{ u.latitude }},{{ u.longitude }}" target="_blank" class="btn-location">📍 View Location</a>
              <div style="font-size: 0.75rem; color: #94a3b8; margin-top: 6px;">
                🕒 {{ u.last_location_update }}
              </div>
            {% else %}
              <span style="color: #64748b; font-size: 0.85rem; font-style: italic;">No Location</span>
            {% endif %}
          </td>
          <td>
            <button class="btn-action btn-edit" onclick='openEditProfileModal({{ u.username|tojson }}, {{ prof|tojson }})'>✏️ এডিট</button>
            <button class="btn-action btn-reset" onclick="adminResetPass('{{ u.username }}')">🔑 রিসেট</button>
            <button class="btn-action btn-del" onclick="adminDeleteUser('{{ u.username }}')">🗑️ ডিলিট</button>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>

<!-- ✏️ ইউজার প্রোফাইল এডিট মডাল -->
<div class="modal" id="editProfileModal">
  <div class="modal-content">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
      <div class="modal-title" id="editModalUserTitle">প্রোফাইল এডিট</div>
      <span style="cursor: pointer; color: var(--danger); font-size: 1.5rem; font-weight: bold;" onclick="closeModal('editProfileModal')">×</span>
    </div>
    <input type="hidden" id="editTargetUser">

    <label>ফিটনেস লক্ষ্য (Goal):</label>
    <select id="editGoal">
      <option value="lose">ওজন কমানো (Lose Weight)</option>
      <option value="gain">ওজন বাড়ানো (Gain Weight)</option>
      <option value="maintain">ওজন ধরে রাখা (Maintain)</option>
    </select>

    <label>লিঙ্গ (Gender):</label>
    <select id="editGender">
      <option value="male">পুরুষ (Male)</option>
      <option value="female">মহিলা (Female)</option>
    </select>

    <label>জন্মতারিখ (Date of Birth):</label>
    <input type="date" id="editDob">

    <label>উচ্চতা (Feet & Inches):</label>
    <div style="display: flex; gap: 8px;">
      <input type="number" id="editHeightFeet" placeholder="Feet">
      <input type="number" id="editHeightInches" placeholder="Inches">
    </div>

    <label>বর্তমান ওজন (কেজি):</label>
    <input type="number" id="editWeight" step="0.1" placeholder="Current Weight">

    <label>টার্গেট ওজন (কেজি):</label>
    <input type="number" id="editTargetWeight" step="0.1" placeholder="Target Weight">

    <button class="btn-primary" style="width: 100%; margin-top: 10px;" onclick="saveAdminUserProfile()">সেভ ও অটো-ক্যালকুলেট</button>
  </div>
</div>

<!-- 🔐 অ্যাডমিন পাসওয়ার্ড পরিবর্তন মডাল -->
<div class="modal" id="adminPassModal">
  <div class="modal-content">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
      <div class="modal-title">অ্যাডমিন পাসওয়ার্ড পরিবর্তন</div>
      <span style="cursor: pointer; color: var(--danger); font-size: 1.5rem; font-weight: bold;" onclick="closeModal('adminPassModal')">×</span>
    </div>
    <label>নতুন পাসওয়ার্ড দিন:</label>
    <input type="password" id="newAdminPassInput" placeholder="Enter New Admin Password">
    <button class="btn-primary" style="width: 100%;" onclick="changeAdminPassword()">পাসওয়ার্ড আপডেট করুন</button>
  </div>
</div>

<script>
function closeModal(id) { document.getElementById(id).style.display = 'none'; }
function openAdminPassModal() {
  document.getElementById('newAdminPassInput').value = '';
  document.getElementById('adminPassModal').style.display = 'flex';
}

function openEditProfileModal(username, profile) {
  document.getElementById('editTargetUser').value = username;
  document.getElementById('editModalUserTitle').innerText = `প্রোফাইল এডিট: ${username}`;
  document.getElementById('editGoal').value = profile.goal || 'lose';
  document.getElementById('editGender').value = profile.gender || 'male';
  document.getElementById('editDob').value = profile.dob || '';
  document.getElementById('editHeightFeet').value = profile.heightFeet || '';
  document.getElementById('editHeightInches').value = profile.heightInches || '';
  document.getElementById('editWeight').value = profile.lastWeight || '';
  document.getElementById('editTargetWeight').value = profile.targetWeight || '';
  document.getElementById('editProfileModal').style.display = 'flex';
}

async function saveAdminUserProfile() {
  const username = document.getElementById('editTargetUser').value;
  const goal = document.getElementById('editGoal').value;
  const gender = document.getElementById('editGender').value;
  const dob = document.getElementById('editDob').value;
  const feet = parseInt(document.getElementById('editHeightFeet').value) || 0;
  const inches = parseInt(document.getElementById('editHeightInches').value) || 0;
  const weight = parseFloat(document.getElementById('editWeight').value) || 0;
  const targetWeight = parseFloat(document.getElementById('editTargetWeight').value) || 0;

  if (!weight || !feet) { alert("উচ্চতা এবং ওজন দেওয়া আবশ্যক!"); return; }

  const res = await fetch('/admin/api/update-user-profile', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ username, goal, gender, dob, feet, inches, weight, targetWeight })
  });
  if (res.ok) {
    alert("ইউজারের প্রোফাইল সফলভাবে আপডেট হয়েছে!");
    location.reload();
  } else {
    alert("আপডেট করতে সমস্যা হয়েছে!");
  }
}

async function changeAdminPassword() {
  const newPass = document.getElementById('newAdminPassInput').value.trim();
  if (!newPass) { alert("পাসওয়ার্ড ফাঁকা রাখা যাবে না!"); return; }
  const res = await fetch('/admin/api/change-admin-password', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ new_password: newPass })
  });
  if (res.ok) {
    alert("অ্যাডমিন পাসওয়ার্ড সফলভাবে পরিবর্তিত হয়েছে! পরবর্তী লগইনে এটি ব্যবহার করুন।");
    closeModal('adminPassModal');
  } else {
    alert("পাসওয়ার্ড পরিবর্তন ব্যর্থ হয়েছে!");
  }
}

async function adminResetPass(username) {
  const newPass = prompt(`"${username}" ইউজারের জন্য নতুন পাসওয়ার্ড দিন:`);
  if (!newPass) return;
  const res = await fetch('/admin/api/reset-user', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ username, new_password: newPass })
  });
  if (res.ok) { alert("পাসওয়ার্ড সফলভাবে পরিবর্তন হয়েছে!"); location.reload(); }
}

async function adminDeleteUser(username) {
  if (!confirm(`সতর্কতা: আপনি কি নিশ্চিত যে "${username}" ইউজারকে স্থায়ীভাবে ডিলিট করতে চান?`)) return;
  const res = await fetch('/admin/api/delete-user', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ username })
  });
  if (res.ok) { alert("ইউজার সফলভাবে ডিলিট করা হয়েছে!"); location.reload(); }
}
</script>
</body>
</html>
"""

ADMIN_LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin Login - FitPulse</title>
<style>
body { background: #0b0f0c; color: #e2e8f0; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; font-family: sans-serif; }
.card { background: rgba(22, 27, 24, 0.85); border: 1px solid rgba(132, 204, 22, 0.3); padding: 35px 25px; border-radius: 20px; width: 100%; max-width: 360px; text-align: center; }
input { width: 100%; padding: 12px; margin-bottom: 12px; background: rgba(0,0,0,0.5); border: 1px solid rgba(132, 204, 22, 0.3); border-radius: 10px; color: #fff; box-sizing: border-box; outline: none; }
button { width: 100%; padding: 12px; background: #84cc16; color: #000; border: none; border-radius: 10px; font-weight: bold; cursor: pointer; }
.toggle-btn { margin-top: 14px; font-size: 0.85rem; color: #84cc16; cursor: pointer; text-decoration: underline; }
</style>
</head>
<body>
<div class="card">
  <div id="adminLoginFormView">
    <h2 style="color: #84cc16; margin-bottom: 20px;">Admin Access</h2>
    {% if error %}<div style="color:#ef4444; font-size:0.85rem; margin-bottom:12px;">{{ error }}</div>{% endif %}
    {% if msg %}<div style="color:#84cc16; font-size:0.85rem; margin-bottom:12px;">{{ msg }}</div>{% endif %}
    <form action="/admin" method="POST">
      <input type="hidden" name="action_type" value="login">
      <input type="text" name="username" placeholder="Admin Username (admin)" required>
      <input type="password" name="password" placeholder="Admin Password" required>
      <button type="submit">লগইন করুন</button>
    </form>
    <div class="toggle-btn" onclick="toggleAdminViews('reset')">পাসওয়ার্ড ভুলে গেছেন?</div>
  </div>

  <div id="adminResetFormView" style="display: none;">
    <h2 style="color: #84cc16; margin-bottom: 15px;">Admin Password Reset</h2>
    <p style="font-size:0.8rem; color:#94a3b8; margin-bottom:15px;">পাসওয়ার্ড রিসেট করতে মাস্টার কী প্রদান করুন।</p>
    <form action="/admin" method="POST">
      <input type="hidden" name="action_type" value="reset">
      <input type="password" name="master_key" placeholder="Master Recovery Key" required>
      <input type="password" name="new_password" placeholder="New Admin Password" required>
      <button type="submit">পাসওয়ার্ড রিসেট করুন</button>
    </form>
    <div class="toggle-btn" onclick="toggleAdminViews('login')" style="color:#94a3b8;">⬅ লগইনে ফিরে যান</div>
  </div>
</div>

<script>
function toggleAdminViews(mode) {
  if (mode === 'reset') {
    document.getElementById('adminLoginFormView').style.display = 'none';
    document.getElementById('adminResetFormView').style.display = 'block';
  } else {
    document.getElementById('adminLoginFormView').style.display = 'block';
    document.getElementById('adminResetFormView').style.display = 'none';
  }
}
</script>
</body>
</html>
"""

@app.route('/admin', methods=['GET', 'POST'])
def admin_portal():
    error = None
    msg = None
    if request.method == 'POST':
        action_type = request.form.get('action_type', 'login')

        if action_type == 'login':
            u = request.form.get('username', '').strip().lower()
            p = request.form.get('password', '').strip()
            current_admin_hash = get_admin_pass_hash()

            if u == "admin" and hash_password(p) == current_admin_hash:
                session['is_admin_portal'] = True
            else:
                error = "ভুল অ্যাডমিন ইউজারনেম বা পাসওয়ার্ড!"

        elif action_type == 'reset':
            master_key = request.form.get('master_key', '').strip()
            new_p = request.form.get('new_password', '').strip()

            if master_key == ADMIN_RECOVERY_MASTER_KEY:
                if new_p:
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute('INSERT OR REPLACE INTO admin_config (key, val) VALUES (?, ?)', ('admin_pass', hash_password(new_p)))
                    conn.commit()
                    conn.close()
                    msg = "অ্যাডমিন পাসওয়ার্ড সফলভাবে রিসেট হয়েছে! এখন লগইন করুন।"
                else:
                    error = "নতুন পাসওয়ার্ড ফাঁকা রাখা যাবে না!"
            else:
                error = "ভুল মাস্টার রিকভারি কী (Invalid Recovery Key)!"

    if not session.get('is_admin_portal'):
        return render_template_string(ADMIN_LOGIN_HTML, error=error, msg=msg)

    conn = get_db_connection()
    c = conn.cursor()
    raw_users = c.execute('SELECT * FROM users').fetchall()
    conn.close()

    users = []
    for u in raw_users:
        try: prof = json.loads(u['profile'])
        except: prof = {}
        try: hist = json.loads(u['history'])
        except: hist = {}

        users.append({
            "username": u['username'],
            "password": u['password'],
            "profile_data": prof,
            "history_days": len(hist.keys()),
            "latitude": u['latitude'] if 'latitude' in u.keys() else None,
            "longitude": u['longitude'] if 'longitude' in u.keys() else None,
            "altitude": u['altitude'] if 'altitude' in u.keys() else None,
            "last_location_update": u['last_location_update'] if 'last_location_update' in u.keys() else None
        })

    return render_template_string(ADMIN_DASHBOARD_HTML, users=users)

@app.route('/admin/logout', methods=['POST', 'GET'])
def admin_logout():
    session.pop('is_admin_portal', None)
    return redirect('/admin')

@app.route('/admin/api/change-admin-password', methods=['POST'])
def change_admin_password():
    if not session.get('is_admin_portal'): return jsonify({"status": "error"}), 403
    data = request.get_json(force=True) or {}
    new_p = data.get('new_password', '').strip()
    if not new_p: return jsonify({"status": "error"}), 400

    conn = get_db_connection()
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO admin_config (key, val) VALUES (?, ?)', ('admin_pass', hash_password(new_p)))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/admin/api/update-user-profile', methods=['POST'])
def admin_update_user_profile():
    if not session.get('is_admin_portal'): return jsonify({"status": "error"}), 403
    data = request.get_json(force=True) or {}
    username = data.get('username')
    if not username: return jsonify({"status": "error"}), 400

    conn = get_db_connection()
    c = conn.cursor()
    user = c.execute('SELECT profile FROM users WHERE username = ?', (username,)).fetchone()
    if not user:
        conn.close()
        return jsonify({"status": "error", "message": "User not found"}), 404

    try:
        prof = json.loads(user['profile'])
    except:
        prof = {}

    goal = data.get('goal', 'lose')
    gender = data.get('gender', 'male')
    dob = data.get('dob', '')
    feet = int(data.get('feet', 0))
    inches = int(data.get('inches', 0))
    weight = float(data.get('weight', 0))
    targetWeight = float(data.get('targetWeight', 0))

    age = 20
    if dob:
        try:
            from datetime import datetime
            birth_year = datetime.strptime(dob, '%Y-%m-%d').year
            age = 2026 - birth_year
        except:
            pass

    height_cm = ((feet * 12) + inches) * 2.54
    bmr = (10 * weight) + (6.25 * height_cm) - (5 * age) + 5 if gender == 'male' else (10 * weight) + (6.25 * height_cm) - (5 * age) - 161
    tdee = bmr * 1.2

    if goal == 'lose': target_cal = tdee - 500
    elif goal == 'gain': target_cal = tdee + 400
    else: target_cal = tdee

    final_target_cal = max(1200, round(target_cal))
    protein_mult = 1.8 if goal == 'gain' else 1.6
    max_sugar = 25 if gender == 'female' else 36

    prof.update({
        "setupComplete": True,
        "goal": goal,
        "gender": gender,
        "dob": dob,
        "age": age,
        "heightFeet": feet,
        "heightInches": inches,
        "lastWeight": weight,
        "targetWeight": targetWeight,
        "targetCal": final_target_cal,
        "targetProtein": round(weight * protein_mult),
        "targetFat": round((final_target_cal * 0.25) / 9),
        "targetSugar": max_sugar,
        "targetWater": round(weight * 0.033, 1),
        "calculatedBMR": round(bmr)
    })

    c.execute('UPDATE users SET profile = ? WHERE username = ?', (json.dumps(prof, ensure_ascii=False), username))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/admin/api/reset-user', methods=['POST'])
def admin_api_reset():
    if not session.get('is_admin_portal'): return jsonify({"status": "error"}), 403
    data = request.get_json(force=True) or {}
    u = data.get('username')
    p = data.get('new_password')
    if not u or not p: return jsonify({"status": "error"}), 400
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE users SET password = ? WHERE username = ?', (hash_password(p), u))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/admin/api/delete-user', methods=['POST'])
def admin_api_delete():
    if not session.get('is_admin_portal'): return jsonify({"status": "error"}), 403
    data = request.get_json(force=True) or {}
    u = data.get('username')
    if not u: return jsonify({"status": "error"}), 400
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('DELETE FROM users WHERE username = ?', (u,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
import os, sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, flash
from werkzeug.utils import secure_filename
from PIL import Image

app = Flask(__name__)
app.secret_key = "myway_2026_full_control"

# --- PATH CONFIGURATION ---
# This ensures Render finds your folders and database correctly
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
DB_PATH = os.path.join(BASE_DIR, "database.db")

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Ensure upload folder exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# --- SETTINGS ---
ADMIN_PASS = "202601"
HUB_PIN = "5008"

# --- DATABASE HELPERS ---
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Builds the database tables if they are missing on the server."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS boarding (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                name TEXT, location TEXT, price INTEGER,
                phone TEXT, institution TEXT, distance TEXT,
                images TEXT, map_url TEXT, amenities TEXT, verified INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schools (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                name TEXT UNIQUE, lat TEXT, lng TEXT
            )
        """)
        conn.commit()

# --- TRIGGER INITIALIZATION ---
# This is critical: It runs for Gunicorn on Render, not just local python
init_db()

# --- HELPER: IMAGE OPTIMIZER ---
def save_optimized_image(file):
    unique_name = f"{os.urandom(3).hex()}_{secure_filename(file.filename.rsplit('.', 1)[0])}.webp"
    path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
    
    img = Image.open(file)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    
    img.thumbnail((1200, 1200))
    img.save(path, "WEBP", quality=80)
    return unique_name

# --- PWA SERVICE WORKER ROUTE ---
@app.route('/sw.js')
def serve_sw():
    # Looks for sw.js in your 'static' folder
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

# 1. STUDENT VIEW
@app.route("/")
def index():
    conn = get_db()
    houses = conn.execute("SELECT * FROM boarding WHERE verified = 1 ORDER BY id DESC").fetchall()
    schools = conn.execute("SELECT * FROM schools ORDER BY name ASC").fetchall()
    conn.close()
    return render_template("index.html", houses=houses, schools=schools)

# 2. LANDLORD HUB
@app.route("/landlord", methods=["GET", "POST"])
def landlord():
    if not session.get("hub_unlocked"):
        if request.method == "POST":
            if request.form.get("hub_password") == HUB_PIN:
                session["hub_unlocked"] = True
                return redirect(url_for("landlord"))
            else:
                return render_template("landlord_login.html", error="Invalid Access PIN")
        return render_template("landlord_login.html")

    conn = get_db()
    if request.method == "POST":
        files = request.files.getlist("photos")
        saved_names = []
        for file in files:
            if file and file.filename != '':
                try:
                    unique_name = save_optimized_image(file)
                    saved_names.append(unique_name)
                except Exception as e:
                    print(f"Error processing image: {e}")
        
        conn.execute("""
            INSERT INTO boarding (name, location, price, phone, institution, distance, images, map_url, amenities, verified) 
            VALUES (?,?,?,?,?,?,?,?,?,0)""",
            (request.form.get("name"), request.form.get("location"), request.form.get("price"), 
             request.form.get("phone"), "|".join(request.form.getlist("institution")), request.form.get("distance"), 
             ",".join(saved_names), request.form.get("map_url"), ",".join(request.form.getlist("amenities"))))
        conn.commit()
        conn.close()
        flash("Property submitted! It will appear once verified by admin.", "info")
        return redirect(url_for('index'))
    
    schools = conn.execute("SELECT * FROM schools ORDER BY name ASC").fetchall()
    conn.close()
    return render_template("landlord.html", schools=schools)

# 3. ADMIN CONSOLE
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not session.get("is_admin"):
        if request.method == "POST":
            if request.form.get("admin_password") == ADMIN_PASS:
                session["is_admin"] = True
                return redirect(url_for("admin"))
            else:
                return render_template("admin_login.html", error="Incorrect Admin Password")
        return render_template("admin_login.html")

    conn = get_db()
    if request.method == "POST":
        house_id = request.form.get("id")
        if "verify" in request.form:
            conn.execute("UPDATE boarding SET verified = 1 WHERE id = ?", (house_id,))
            flash(f"House #{house_id} is now LIVE.", "success")
        elif "delete" in request.form:
            house = conn.execute("SELECT images FROM boarding WHERE id = ?", (house_id,)).fetchone()
            if house['images']:
                for img_name in house['images'].split(','):
                    img_path = os.path.join(app.config['UPLOAD_FOLDER'], img_name)
                    if os.path.exists(img_path):
                        os.remove(img_path)
            conn.execute("DELETE FROM boarding WHERE id = ?", (house_id,))
            flash(f"House #{house_id} deleted successfully.", "danger")
        elif "add_school" in request.form:
            conn.execute("INSERT OR IGNORE INTO schools (name, lat, lng) VALUES (?, ?, ?)", 
                         (request.form["school_name"], request.form["lat"], request.form["lng"]))
        conn.commit()
    
    houses = conn.execute("SELECT * FROM boarding ORDER BY verified ASC, id DESC").fetchall()
    schools = conn.execute("SELECT * FROM schools ORDER BY name ASC").fetchall()
    conn.close()
    return render_template("admin.html", houses=houses, schools=schools)

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True, port=5000, host='0.0.0.0')

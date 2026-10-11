"""úricoimm - Flask + MySQL. Ejecuta: python app.py"""
import os, smtplib, threading, unicodedata, uuid, webbrowser
from dotenv import load_dotenv
load_dotenv()
from email.message import EmailMessage
from functools import wraps
from flask import (Flask, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
import mysql.connector

app = Flask(__name__)
PORT = 5050
BASE = os.path.dirname(os.path.abspath(__file__))

# Clave de sesión (cámbiala con la variable de entorno URICO_SECRET)
app.secret_key = os.getenv("URICO_SECRET", "uricoimm-cambia-esta-clave-secreta")

# Credenciales admin iniciales (cámbialas desde el panel / variables de entorno)
ADMIN_USER = os.getenv("URICO_ADMIN_USER", "admin11133")
ADMIN_PASS = os.getenv("URICO_ADMIN_PASS", "admin321321")

# Config SMTP por variables de entorno (ej. Gmail con contraseña de aplicación)
SMTP_HOST = os.getenv("URICO_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("URICO_SMTP_PORT", "587"))
SMTP_USER = os.getenv("URICO_SMTP_USER", "")
SMTP_PASS = os.getenv("URICO_SMTP_PASS", "")

# Config MySQL por variables de entorno (ver schema.sql)
DB_HOST = os.getenv("URICO_DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("URICO_DB_PORT", "3306"))
DB_USER = os.getenv("URICO_DB_USER", "uricoimm")
DB_PASS = os.getenv("URICO_DB_PASS", "CambiaEstaClave123!")
DB_NAME = os.getenv("URICO_DB_NAME", "uricoimm")

def norm(t):
    t = unicodedata.normalize("NFD", t.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn").strip()

def nivel(p):
    # purinas mg/100 g: <50 bajo, 50-150 medio, >150 alto
    if p >= 150: return "alto", "rojo", "🚩 Muy dañino"
    if p >= 50:  return "medio", "amarillo", "🟡 Daño medio"
    return "bajo", "verde", "🟢 No dañino"

def get_db():
    """Abre una conexión nueva a MySQL."""
    return mysql.connector.connect(host=DB_HOST, port=DB_PORT, user=DB_USER,
                                   password=DB_PASS, database=DB_NAME, charset="utf8mb4")

def consultar(sql, params=None):
    """Ejecuta un SELECT y devuelve todas las filas."""
    con = get_db()
    try:
        cur = con.cursor()
        cur.execute(sql, params) if params is not None else cur.execute(sql)
        return cur.fetchall()
    finally:
        con.close()

def ejecutar(sql, params=None):
    """Ejecuta un INSERT/UPDATE/DELETE y confirma la transacción."""
    con = get_db()
    try:
        cur = con.cursor()
        cur.execute(sql, params) if params is not None else cur.execute(sql)
        con.commit()
        return cur.lastrowid
    finally:
        con.close()

def item(nombre, categoria, purinas):
    p = float(purinas); n, c, e = nivel(p)
    return {"nombre": nombre, "categoria": categoria, "purinas": p,
            "nivel": n, "color": c, "etiqueta": e,
            "porcentaje": min(100, round(p / 4)), "_k": norm(nombre)}

def limpio(i): return {k: v for k, v in i.items() if k != "_k"}

# ---------- Autenticación ----------
def login_requerido(f):
    @wraps(f)
    def envoltura(*a, **k):
        if not session.get("admin"):
            return redirect(url_for("lg"))
        return f(*a, **k)
    return envoltura

def asegurar_admin():
    """Crea el admin inicial si no existe (no sobreescribe si ya cambió la clave)."""
    try:
        if not consultar("SELECT id FROM admins WHERE usuario = %s", (ADMIN_USER,)):
            ejecutar("INSERT INTO admins (usuario, password_hash) VALUES (%s, %s)",
                     (ADMIN_USER, generate_password_hash(ADMIN_PASS)))
            print(f"Admin inicial creado: {ADMIN_USER}")
    except Exception as e:
        print(f"Aviso: no se pudo verificar/crear el admin (¿corriste schema.sql?): {e}")

def registrar_visita():
    """Cuenta una visita a la página pública (visitante anónimo por cookie)."""
    if "vid" not in session:
        session["vid"] = uuid.uuid4().hex
    try:
        ejecutar("INSERT INTO visitas (visitante, ip, agente, ruta) VALUES (%s, %s, %s, %s)",
                 (session["vid"], request.remote_addr or "", (request.user_agent.string or "")[:255],
                  request.path[:255]))
    except Exception:
        pass

def sin_cache(resp):
    if resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp

# ---------- Sitio público ----------
@app.route("/img/<path:filename>")
def img(filename):
    return send_from_directory(os.path.join(BASE, "img"), filename)

@app.route("/")
def index():
    registrar_visita()
    total = consultar("SELECT COUNT(*) FROM alimentos")[0][0]
    return render_template("index.html", total=total)

@app.route("/acido-urico")
def acido_urico():
    registrar_visita()
    total = consultar("SELECT COUNT(*) FROM alimentos")[0][0]
    return render_template("acido-urico.html", total=total)

@app.route("/preguntas")
def preguntas():
    registrar_visita()
    total = consultar("SELECT COUNT(*) FROM alimentos")[0][0]
    return render_template("preguntas.html", total=total)

@app.route("/y-ahora-que-hago")
def y_ahora_que_hago():
    registrar_visita()
    total = consultar("SELECT COUNT(*) FROM alimentos")[0][0]
    return render_template("y-ahora-que-hago.html", total=total)

@app.route("/mitos-y-realidades")
def mitos_y_realidades():
    registrar_visita()
    total = consultar("SELECT COUNT(*) FROM alimentos")[0][0]
    return render_template("mitos-y-realidades.html", total=total)

@app.route("/api/sugerir")
def sugerir():
    q = norm(request.args.get("q", ""))
    cat = request.args.get("cat", "")
    if not q: return jsonify([])
    filas = consultar(
        "SELECT a.nombre, c.nombre, a.purinas "
        "FROM alimentos a JOIN categorias c ON c.id = a.categoria_id "
        "WHERE (%s = '' OR c.nombre = %s) AND a.nombre_norm LIKE %s "
        "ORDER BY (a.nombre_norm LIKE %s) DESC, a.nombre_norm "
        "LIMIT 10",
        (cat, cat, f"%{q}%", f"{q}%"))
    return jsonify([limpio(item(*f)) for f in filas])

@app.route("/api/enviar", methods=["POST"])
def enviar():
    d = request.get_json(force=True)
    dest, items = d.get("correo", "").strip(), d.get("items", [])
    if "@" not in dest or not items: return jsonify(ok=False, msg="Correo o consulta vacíos"), 400
    if not SMTP_USER: return jsonify(ok=False, msg="Configura URICO_SMTP_USER y URICO_SMTP_PASS"), 500
    cuerpo = "Consulta úricoimm (purinas aprox. mg/100 g)\n\n" + "\n".join(
        f"- {i['nombre']} ({i['categoria']}): {i['purinas']:g} mg → {i['etiqueta']}" for i in items)
    cuerpo += "\n\nInformación orientativa; consulta a tu médico o nutriólogo."
    m = EmailMessage(); m["Subject"] = "Tu consulta de úricoimm"; m["From"] = SMTP_USER; m["To"] = dest
    m.set_content(cuerpo)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            s.starttls(); s.login(SMTP_USER, SMTP_PASS); s.send_message(m)
    except Exception as e:
        return jsonify(ok=False, msg=f"Error SMTP: {e}"), 500
    return jsonify(ok=True)

@app.route("/api/newsletter", methods=["POST"])
def newsletter():
    d = request.get_json(silent=True) or {}
    mensaje = (d.get("mensaje") or "").strip()
    if len(mensaje) < 3:
        return jsonify(ok=False, msg="Escribe tu mensaje."), 400
    ip = request.remote_addr or ""
    # Límite anti-spam: máximo 20 mensajes por IP en 10 minutos.
    try:
        contador = consultar(
            "SELECT COUNT(*) FROM mensajes WHERE ip = %s AND creado_en > NOW() - INTERVAL %s MINUTE",
            (ip, 10))[0][0]
        if contador >= 20:
            return jsonify(ok=False, msg="Demasiados envíos. Intenta de nuevo más tarde."), 429
        ejecutar("INSERT INTO mensajes (mensaje, ip) VALUES (%s, %s)", (mensaje[:2000], ip))
    except Exception as e:
        return jsonify(ok=False, msg="Error al guardar el mensaje."), 500
    return jsonify(ok=True)

# ---------- Panel de administración ----------
@app.route("/login", methods=["GET", "POST"])
def lg():
    if session.get("admin"):
        return redirect(url_for("admin_panel"))
    error = None
    if request.method == "POST":
        usuario = (request.form.get("usuario") or "").strip()
        clave = request.form.get("password") or ""
        fila = consultar("SELECT password_hash FROM admins WHERE usuario = %s", (usuario,))
        if fila and check_password_hash(fila[0][0], clave):
            vid = session.get("vid")
            session.clear()
            session["admin"] = usuario
            if vid: session["vid"] = vid
            return redirect(url_for("admin_panel"))
        error = "Usuario o contraseña incorrectos."
    return render_template("LG.html", error=error)

@app.route("/logout")
def logout():
    vid = session.get("vid")
    session.clear()
    if vid: session["vid"] = vid
    return redirect(url_for("lg"))

@app.route("/admin")
@login_requerido
def admin_panel():
    total        = consultar("SELECT COUNT(*) FROM visitas")[0][0]
    visitantes   = consultar("SELECT COUNT(DISTINCT visitante) FROM visitas")[0][0]
    hoy          = consultar("SELECT COUNT(*) FROM visitas WHERE DATE(creado_en) = CURDATE()")[0][0]
    visitantes_h = consultar("SELECT COUNT(DISTINCT visitante) FROM visitas WHERE DATE(creado_en) = CURDATE()")[0][0]
    ultimas = consultar(
        "SELECT DATE_FORMAT(creado_en, '%Y-%m-%d %H:%i:%s'), ip, ruta, agente "
        "FROM visitas ORDER BY id DESC LIMIT 20")
    try:
        mensajes = consultar(
            "SELECT DATE_FORMAT(creado_en, '%Y-%m-%d %H:%i:%s'), ip, mensaje "
            "FROM mensajes ORDER BY id DESC LIMIT 50")
    except Exception:
        mensajes = []
    return render_template("admin.html", usuario=session["admin"],
                           total_visitas=total, visitantes=visitantes,
                           visitas_hoy=hoy, visitantes_hoy=visitantes_h,
                           ultimas=ultimas, mensajes=mensajes,
                           ok=request.args.get("ok"), error=request.args.get("error"))

@app.route("/admin/password", methods=["POST"])
@login_requerido
def cambiar_password():
    actual  = request.form.get("actual") or ""
    nueva   = request.form.get("nueva") or ""
    repetir = request.form.get("repetir") or ""
    fila = consultar("SELECT password_hash FROM admins WHERE usuario = %s", (session["admin"],))
    if not fila or not check_password_hash(fila[0][0], actual):
        return redirect(url_for("admin_panel", error="La contraseña actual no es correcta."))
    if len(nueva) < 8:
        return redirect(url_for("admin_panel", error="La nueva contraseña debe tener al menos 8 caracteres."))
    if nueva != repetir:
        return redirect(url_for("admin_panel", error="La nueva contraseña no coincide con la repetición."))
    ejecutar("UPDATE admins SET password_hash = %s WHERE usuario = %s",
             (generate_password_hash(nueva), session["admin"]))
    return redirect(url_for("admin_panel", ok="Contraseña actualizada correctamente."))

@app.route("/admin/reset-visitas", methods=["POST"])
@login_requerido
def reset_visitas():
    try:
        ejecutar("DELETE FROM visitas")
    except Exception as e:
        return redirect(url_for("admin_panel", error=f"Error al borrar: {e}"))
    return redirect(url_for("admin_panel", ok="Contador de visitas puesto en cero."))

@app.after_request
def _headers(resp):
    return sin_cache(resp)

if __name__ == "__main__":
    asegurar_admin()
    print(f"úricoimm activo en http://127.0.0.1:{PORT}  (Ctrl+C para detener)")
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    app.run(host="127.0.0.1", port=PORT, debug=False)

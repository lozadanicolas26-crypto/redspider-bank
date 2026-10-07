from fastapi import FastAPI, HTTPException, Form, Depends
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from uuid import UUID, uuid4
from passlib.hash import bcrypt
from psycopg2.pool import ThreadedConnectionPool
from starlette.requests import Request

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

import os
pool = ThreadedConnectionPool(2, 20, os.environ.get("DATABASE_URL", "postgres://postgres:banco123@localhost:5432/banco"))


def db():
    return pool.getconn()


def liberar(conn):
    pool.putconn(conn)


@app.get("/", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(cedula: str = Form(...), clave: str = Form(...)):
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, nombre, clave_hash FROM usuarios WHERE cedula=%s", (cedula,))
            fila = cur.fetchone()
        if not fila or not bcrypt.verify(clave, fila[2]):
            raise HTTPException(401, "Cédula o clave incorrecta")
        return {"ok": True, "usuario_id": fila[0], "nombre": fila[1]}
    finally:
        liberar(conn)


@app.post("/registro")
def registro(cedula: str = Form(...), nombre: str = Form(...), clave: str = Form(...)):
    conn = db()
    try:
        with conn:
            with conn.cursor() as cur:
                clave_hash = bcrypt.hash(clave)
                cur.execute("INSERT INTO usuarios (cedula, nombre, clave_hash) VALUES (%s,%s,%s) RETURNING id",
                            (cedula, nombre, clave_hash))
                usuario_id = cur.fetchone()[0]
                cur.execute("INSERT INTO cuentas (usuario_id, saldo) VALUES (%s, 0)", (usuario_id,))
        return {"ok": True, "usuario_id": usuario_id}
    finally:
        liberar(conn)


@app.get("/cuenta/{usuario_id}")
def ver_cuenta(usuario_id: int):
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT c.id, u.nombre, c.saldo FROM cuentas c
                           JOIN usuarios u ON u.id = c.usuario_id
                           WHERE c.usuario_id=%s""", (usuario_id,))
            fila = cur.fetchone()
        if not fila:
            raise HTTPException(404, "No existe")
        return {"cuenta_id": fila[0], "nombre": fila[1], "saldo": float(fila[2])}
    finally:
        liberar(conn)


class Transferencia(BaseModel):
    origen: int
    destino: int
    monto: float = Field(gt=0)
    banco_destino: str = "RedSpider Bank"


@app.post("/transferir")
def transferir(t: Transferencia):
    if t.origen == t.destino:
        raise HTTPException(400, "Cuentas iguales")
    conn = db()
    try:
        with conn:
            with conn.cursor() as cur:
                a, b = sorted([t.origen, t.destino])
                cur.execute("SELECT id FROM cuentas WHERE id IN (%s,%s) ORDER BY id FOR UPDATE", (a, b))

                cur.execute("UPDATE cuentas SET saldo = saldo - %s WHERE id=%s AND saldo >= %s",
                            (t.monto, t.origen, t.monto))
                if cur.rowcount == 0:
                    raise HTTPException(422, "Saldo insuficiente")

                cur.execute("UPDATE cuentas SET saldo = saldo + %s WHERE id=%s", (t.monto, t.destino))

                tid = str(uuid4())
                cur.execute("""INSERT INTO transferencias (id,cuenta_origen,cuenta_destino,banco_destino,monto)
                               VALUES (%s,%s,%s,%s,%s)""", (tid, t.origen, t.destino, t.banco_destino, t.monto))
                cur.execute("""INSERT INTO movimientos (cuenta_id,transf_id,monto,descripcion) VALUES
                               (%s,%s,%s,'Transferencia enviada'),(%s,%s,%s,'Transferencia recibida')""",
                            (t.origen, tid, -t.monto, t.destino, tid, t.monto))
        return {"ok": True}
    finally:
        liberar(conn)


class SolicitudCredito(BaseModel):
    usuario_id: int
    monto: float = Field(gt=0)
    plazo_meses: int = Field(gt=0)


@app.post("/creditos/solicitar")
def solicitar_credito(s: SolicitudCredito):
    conn = db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO creditos (usuario_id, monto, plazo_meses, estado)
                               VALUES (%s,%s,%s,'pendiente') RETURNING id""",
                            (s.usuario_id, s.monto, s.plazo_meses))
                credito_id = cur.fetchone()[0]
        return {"ok": True, "credito_id": credito_id, "estado": "pendiente"}
    finally:
        liberar(conn)


@app.get("/creditos/{usuario_id}")
def ver_creditos(usuario_id: int):
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, monto, plazo_meses, estado FROM creditos WHERE usuario_id=%s", (usuario_id,))
            filas = cur.fetchall()
        return [{"id": f[0], "monto": float(f[1]), "plazo_meses": f[2], "estado": f[3]} for f in filas]
    finally:
        liberar(conn)


# ---------- ADMIN ----------
CLAVE_ADMIN = "admin123"


class AccionCredito(BaseModel):
    credito_id: int
    clave_admin: str


@app.get("/admin/creditos")
def ver_creditos_pendientes(clave_admin: str):
    if clave_admin != CLAVE_ADMIN:
        raise HTTPException(401, "Clave de administrador incorrecta")
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.id, u.nombre, u.cedula, c.monto, c.plazo_meses, c.estado, c.creado_en
                FROM creditos c
                JOIN usuarios u ON u.id = c.usuario_id
                ORDER BY c.creado_en DESC
            """)
            filas = cur.fetchall()
        return [
            {
                "id": f[0], "nombre": f[1], "cedula": f[2],
                "monto": float(f[3]), "plazo_meses": f[4],
                "estado": f[5], "creado_en": f[6].isoformat()
            } for f in filas
        ]
    finally:
        liberar(conn)


@app.post("/admin/creditos/aprobar")
def aprobar_credito(a: AccionCredito):
    if a.clave_admin != CLAVE_ADMIN:
        raise HTTPException(401, "Clave de administrador incorrecta")
    conn = db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT usuario_id, monto, estado FROM creditos WHERE id=%s FOR UPDATE", (a.credito_id,))
                fila = cur.fetchone()
                if not fila:
                    raise HTTPException(404, "Crédito no encontrado")
                usuario_id, monto, estado = fila
                if estado != "pendiente":
                    raise HTTPException(400, f"Este crédito ya está '{estado}'")

                cur.execute("SELECT id FROM cuentas WHERE usuario_id=%s", (usuario_id,))
                cuenta = cur.fetchone()
                if not cuenta:
                    raise HTTPException(404, "El usuario no tiene cuenta")
                cuenta_id = cuenta[0]

                cur.execute("UPDATE cuentas SET saldo = saldo + %s WHERE id=%s", (monto, cuenta_id))
                cur.execute(
                    "INSERT INTO movimientos (cuenta_id, monto, descripcion) VALUES (%s,%s,'Desembolso de crédito aprobado')",
                    (cuenta_id, monto)
                )
                cur.execute("UPDATE creditos SET estado='aprobado' WHERE id=%s", (a.credito_id,))
        return {"ok": True, "mensaje": "Crédito aprobado y dinero desembolsado"}
    finally:
        liberar(conn)


@app.post("/admin/creditos/rechazar")
def rechazar_credito(a: AccionCredito):
    if a.clave_admin != CLAVE_ADMIN:
        raise HTTPException(401, "Clave de administrador incorrecta")
    conn = db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT estado FROM creditos WHERE id=%s FOR UPDATE", (a.credito_id,))
                fila = cur.fetchone()
                if not fila:
                    raise HTTPException(404, "Crédito no encontrado")
                if fila[0] != "pendiente":
                    raise HTTPException(400, f"Este crédito ya está '{fila[0]}'")
                cur.execute("UPDATE creditos SET estado='rechazado' WHERE id=%s", (a.credito_id,))
        return {"ok": True, "mensaje": "Crédito rechazado"}
    finally:
        liberar(conn)
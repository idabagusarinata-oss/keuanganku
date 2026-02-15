import psycopg2
import os
import matplotlib.pyplot as plt
from datetime import datetime, time, timezone, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib import pagesizes
import smtplib
from email.message import EmailMessage

# ================= ENV =================
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID"))
DATABASE_URL = os.environ.get("DATABASE_URL")
EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")

conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

# ================= TABLE =================
cursor.execute("""
CREATE TABLE IF NOT EXISTS pemasukan (
    id SERIAL PRIMARY KEY,
    no_transaksi VARCHAR(50) UNIQUE,
    jumlah BIGINT,
    tanggal DATE
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS pengeluaran (
    id SERIAL PRIMARY KEY,
    no_transaksi VARCHAR(50) UNIQUE,
    keterangan TEXT,
    kategori TEXT,
    jumlah BIGINT,
    merchant TEXT,
    tanggal DATE
)
""")
conn.commit()

# ================= HELPER =================
def validasi_nominal(text):
    return int(text) if text.isdigit() and int(text) > 0 else None

def generate_no(prefix):
    return f"{prefix}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

# ================= KEYBOARD =================
keyboard = [
    ["Pemasukan", "Pengeluaran"],
    ["Cek Saldo", "Pengeluaran Terbesar"],
    ["Grafik Kategori", "Export PDF"],
    ["Reset Keuangan"]
]
reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ================= BACKUP =================
async def weekly_backup(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().strftime("%Y-%m-%d")
    filename = f"backup_{now}.sql"

    with open(filename, "w") as f:
        for table in ["pemasukan", "pengeluaran"]:
            cursor.execute(f"SELECT * FROM {table}")
            for r in cursor.fetchall():
                f.write(f"INSERT INTO {table} VALUES {r};\n")

    await context.bot.send_document(chat_id=ADMIN_ID, document=open(filename,"rb"))

    msg = EmailMessage()
    msg["Subject"] = f"Backup Database {now}"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = "idabagusarinata@gmail.com"
    msg.set_content("Backup database terlampir.")
    with open(filename,"rb") as f:
        msg.add_attachment(f.read(), maintype="application", subtype="octet-stream", filename=filename)
    with smtplib.SMTP_SSL("smtp.gmail.com",465) as server:
        server.login(EMAIL_ADDRESS,EMAIL_PASSWORD)
        server.send_message(msg)

    os.remove(filename)

# ================= BOT =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot Keuangan Aktif ✅", reply_markup=reply_markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id

    # RESET
    if text == "Reset Keuangan":
        if user_id != ADMIN_ID:
            await update.message.reply_text("❌ Anda bukan admin.")
            return
        cursor.execute("TRUNCATE pemasukan, pengeluaran RESTART IDENTITY")
        conn.commit()
        await update.message.reply_text("Data berhasil direset.")
        return

    # CEK SALDO
    if text == "Cek Saldo":
        cursor.execute("SELECT COALESCE(SUM(jumlah),0) FROM pemasukan")
        pemasukan = cursor.fetchone()[0]
        cursor.execute("SELECT COALESCE(SUM(jumlah),0) FROM pengeluaran")
        pengeluaran = cursor.fetchone()[0]
        await update.message.reply_text(f"Saldo: Rp {pemasukan-pengeluaran:,}")
        return

    # PENGELUARAN TERBESAR
    if text == "Pengeluaran Terbesar":
        cursor.execute("SELECT keterangan,jumlah FROM pengeluaran ORDER BY jumlah DESC LIMIT 1")
        data = cursor.fetchone()
        if data:
            await update.message.reply_text(f"{data[0]} - Rp {data[1]:,}")
        else:
            await update.message.reply_text("Belum ada data.")
        return

    # GRAFIK
    if text == "Grafik Kategori":
        cursor.execute("SELECT kategori,SUM(jumlah) FROM pengeluaran GROUP BY kategori")
        data = cursor.fetchall()
        if not data:
            await update.message.reply_text("Belum ada data.")
            return
        kategori = [d[0] for d in data]
        total = [d[1] for d in data]
        plt.figure()
        plt.bar(kategori,total)
        plt.savefig("grafik.png")
        plt.close()
        await update.message.reply_photo(photo=open("grafik.png","rb"))
        os.remove("grafik.png")
        return

    # EXPORT PDF
    if text == "Export PDF":
        filename="laporan.pdf"
        doc=SimpleDocTemplate(filename,pagesize=pagesizes.A4)
        cursor.execute("SELECT * FROM pengeluaran")
        data=cursor.fetchall()
        table_data=[["No","Ket","Kategori","Jumlah","Merchant","Tanggal"]]
        for r in data:
            table_data.append([r[1],r[2],r[3],r[4],r[5],str(r[6])])
        table=Table(table_data)
        table.setStyle(TableStyle([("GRID",(0,0),(-1,-1),1,colors.black)]))
        doc.build([table])
        await update.message.reply_document(open(filename,"rb"))
        os.remove(filename)
        return

    # PEMASUKAN FLOW
    if text == "Pemasukan":
        context.user_data["mode"]="pm_nominal"
        await update.message.reply_text("Masukkan nominal:")
        return

    if context.user_data.get("mode")=="pm_nominal":
        nominal=validasi_nominal(text)
        if not nominal:
            await update.message.reply_text("Masukkan angka valid.")
            return
        context.user_data["jumlah"]=nominal
        context.user_data["mode"]="pm_tanggal"
        await update.message.reply_text("Masukkan tanggal (YYYY-MM-DD):")
        return

    if context.user_data.get("mode")=="pm_tanggal":
        try:
            tanggal=datetime.strptime(text,"%Y-%m-%d").date()
        except:
            await update.message.reply_text("Format salah.")
            return
        no=generate_no("PMK")
        cursor.execute("INSERT INTO pemasukan (no_transaksi,jumlah,tanggal) VALUES (%s,%s,%s)",
                       (no,context.user_data["jumlah"],tanggal))
        conn.commit()
        await update.message.reply_text(f"Pemasukan disimpan ✅\nNo: {no}")
        context.user_data["mode"]=None
        return

    # PENGELUARAN FLOW
    if text == "Pengeluaran":
        context.user_data["mode"]="pg_ket"
        await update.message.reply_text("Belanja apa?")
        return

    if context.user_data.get("mode")=="pg_ket":
        context.user_data["keterangan"]=text
        context.user_data["mode"]="pg_kategori"
        await update.message.reply_text("Kategori?")
        return

    if context.user_data.get("mode")=="pg_kategori":
        context.user_data["kategori"]=text
        context.user_data["mode"]="pg_nominal"
        await update.message.reply_text("Harga?")
        return

    if context.user_data.get("mode")=="pg_nominal":
        nominal=validasi_nominal(text)
        if not nominal:
            await update.message.reply_text("Masukkan angka valid.")
            return
        context.user_data["jumlah"]=nominal
        context.user_data["mode"]="pg_merchant"
        await update.message.reply_text("Merchant?")
        return

    if context.user_data.get("mode")=="pg_merchant":
        context.user_data["merchant"]=text
        context.user_data["mode"]="pg_tanggal"
        await update.message.reply_text("Tanggal (YYYY-MM-DD)?")
        return

    if context.user_data.get("mode")=="pg_tanggal":
        try:
            tanggal=datetime.strptime(text,"%Y-%m-%d").date()
        except:
            await update.message.reply_text("Format salah.")
            return
        no=generate_no("PNG")
        cursor.execute("""
            INSERT INTO pengeluaran
            (no_transaksi,keterangan,kategori,jumlah,merchant,tanggal)
            VALUES (%s,%s,%s,%s,%s,%s)
        """,(no,
             context.user_data["keterangan"],
             context.user_data["kategori"],
             context.user_data["jumlah"],
             context.user_data["merchant"],
             tanggal))
        conn.commit()
        await update.message.reply_text(f"Pengeluaran disimpan ✅\nNo: {no}")
        context.user_data["mode"]=None
        return

# ================= RUN =================
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

wib = timezone(timedelta(hours=7))
app.job_queue.run_daily(weekly_backup, time=time(hour=0,minute=0,tzinfo=wib), days=(6,))

print("Bot berjalan...")
app.run_polling(drop_pending_updates=True)

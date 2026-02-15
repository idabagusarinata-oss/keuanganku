import psycopg2
import os
import matplotlib.pyplot as plt
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import pagesizes

TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID"))

# ================= DATABASE =================
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise Exception("DATABASE_URL not found!")

conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

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

# ================= VALIDASI =================
def validasi_nominal(text):
    if not text.isdigit():
        return None, "❌ Masukkan angka saja."
    jumlah = int(text)
    if jumlah <= 0:
        return None, "❌ Harus lebih dari 0."
    return jumlah, None

# ================= GENERATE NO =================
def generate_no_transaksi(tipe, tanggal):
    tahun_bulan = tanggal.replace("-", "")[:6]
    prefix = "PMK" if tipe == "pemasukan" else "PNG"
    table = "pemasukan" if tipe == "pemasukan" else "pengeluaran"

    cursor.execute(
        f"SELECT COUNT(*) FROM {table} WHERE tanggal >= %s AND tanggal < %s",
        (tanggal[:7] + "-01", tanggal[:7] + "-31")
    )

    count = cursor.fetchone()[0] + 1
    nomor = str(count).zfill(4)
    return f"{prefix}-{tahun_bulan}-{nomor}"

# ================= KEYBOARD =================
keyboard = [
    ["Pemasukan", "Pengeluaran"],
    ["Cek Saldo", "Pengeluaran Terbesar"],
    ["Grafik Kategori", "Export PDF"],
    ["Reset Keuangan"]
]
reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot Keuangan Aktif ✅", reply_markup=reply_markup)

# ================= HANDLE =================
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
        await update.message.reply_text("Semua data berhasil direset.")
        return

    # CEK SALDO
    if text == "Cek Saldo":
        cursor.execute("SELECT COALESCE(SUM(jumlah),0) FROM pemasukan")
        pemasukan = cursor.fetchone()[0]
        cursor.execute("SELECT COALESCE(SUM(jumlah),0) FROM pengeluaran")
        pengeluaran = cursor.fetchone()[0]
        saldo = pemasukan - pengeluaran

        await update.message.reply_text(
            f"Pemasukan: Rp {pemasukan:,}\n"
            f"Pengeluaran: Rp {pengeluaran:,}\n"
            f"Saldo: Rp {saldo:,}"
        )
        return

    # PEMASUKAN
    if text == "Pemasukan":
        context.user_data["mode"] = "pm_jumlah"
        await update.message.reply_text("Masukkan nominal:")
        return

    if context.user_data.get("mode") == "pm_jumlah":
        jumlah, error = validasi_nominal(text)
        if error:
            await update.message.reply_text(error)
            return

        tanggal = datetime.now().strftime("%Y-%m-%d")
        no = generate_no_transaksi("pemasukan", tanggal)

        cursor.execute(
            "INSERT INTO pemasukan (no_transaksi, jumlah, tanggal) VALUES (%s, %s, %s)",
            (no, jumlah, tanggal)
        )
        conn.commit()

        await update.message.reply_text(f"Disimpan ✅\nNo: {no}")
        context.user_data["mode"] = None
        return

    # PENGELUARAN
    if text == "Pengeluaran":
        context.user_data["mode"] = "pg_ket"
        await update.message.reply_text("Belanja apa?")
        return

    if context.user_data.get("mode") == "pg_ket":
        context.user_data["keterangan"] = text
        context.user_data["mode"] = "pg_jumlah"
        await update.message.reply_text("Harga?")
        return

    if context.user_data.get("mode") == "pg_jumlah":
        jumlah, error = validasi_nominal(text)
        if error:
            await update.message.reply_text(error)
            return

        tanggal = datetime.now().strftime("%Y-%m-%d")
        no = generate_no_transaksi("pengeluaran", tanggal)

        cursor.execute("""
            INSERT INTO pengeluaran
            (no_transaksi, keterangan, kategori, jumlah, merchant, tanggal)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            no,
            context.user_data["keterangan"],
            "Umum",
            jumlah,
            "Tidak disebutkan",
            tanggal
        ))
        conn.commit()

        await update.message.reply_text(f"Disimpan ✅\nNo: {no}")
        context.user_data["mode"] = None
        return

# ================= RUN =================
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Bot berjalan...")
app.run_polling(drop_pending_updates=True)

import sqlite3
import matplotlib.pyplot as plt
from datetime import datetime
import shutil
import os

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import pagesizes

TOKEN = "8286781945:AAErYjClrb8JQG0r2ViaZ0z_RLHMqSnVPvU"
ADMIN_ID = 7605783818
DB_NAME = "keuangan.db"

# ================= DATABASE =================
conn = sqlite3.connect(DB_NAME, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS pemasukan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    no_transaksi TEXT UNIQUE,
    jumlah INTEGER,
    tanggal TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS pengeluaran (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    no_transaksi TEXT UNIQUE,
    keterangan TEXT,
    kategori TEXT,
    jumlah INTEGER,
    merchant TEXT,
    tanggal TEXT
)
""")

conn.commit()

# ================= VALIDASI =================
def validasi_nominal(text):
    if not text.isdigit():
        return None, "❌ Masukkan angka saja tanpa titik/koma."
    jumlah = int(text)
    if jumlah <= 0:
        return None, "❌ Nilai harus lebih dari 0."
    if jumlah > 999_999_999:
        return None, "❌ Maksimal 999.999.999"
    return jumlah, None

# ================= GENERATE NO =================
def generate_no_transaksi(tipe, tanggal):
    tahun_bulan = tanggal.replace("-", "")[:6]
    prefix = "PMK" if tipe == "pemasukan" else "PNG"
    table = "pemasukan" if tipe == "pemasukan" else "pengeluaran"

    cursor.execute(f"""
        SELECT COUNT(*) FROM {table}
        WHERE tanggal LIKE ?
    """, (f"{tanggal[:7]}%",))

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

    # ===== RESET =====
    if text == "Reset Keuangan":
        if user_id != ADMIN_ID:
            await update.message.reply_text("❌ Anda bukan admin.")
            return
        context.user_data["mode"] = "confirm_reset"
        await update.message.reply_text("Ketik YA untuk reset semua data.")
        return

    if context.user_data.get("mode") == "confirm_reset":
        if text == "YA":
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = f"backup_{timestamp}.db"
            conn.commit()
            shutil.copy(DB_NAME, backup)
            cursor.execute("DELETE FROM pemasukan")
            cursor.execute("DELETE FROM pengeluaran")
            conn.commit()
            await update.message.reply_document(open(backup, "rb"))
            await update.message.reply_text("Data berhasil direset.")
            os.remove(backup)
        else:
            await update.message.reply_text("Reset dibatalkan.")
        context.user_data["mode"] = None
        return

    # ===== CEK SALDO =====
    if text == "Cek Saldo":
        cursor.execute("SELECT SUM(jumlah) FROM pemasukan")
        pemasukan = cursor.fetchone()[0] or 0
        cursor.execute("SELECT SUM(jumlah) FROM pengeluaran")
        pengeluaran = cursor.fetchone()[0] or 0
        saldo = pemasukan - pengeluaran
        await update.message.reply_text(
            f"Pemasukan: Rp {pemasukan:,}\n"
            f"Pengeluaran: Rp {pengeluaran:,}\n"
            f"Saldo: Rp {saldo:,}"
        )
        return

    # ===== PENGELUARAN TERBESAR =====
    if text == "Pengeluaran Terbesar":
        cursor.execute("""
            SELECT keterangan, jumlah, merchant
            FROM pengeluaran
            ORDER BY jumlah DESC
            LIMIT 1
        """)
        data = cursor.fetchone()
        if data:
            await update.message.reply_text(
                f"{data[0]}\nRp {data[1]:,}\nMerchant: {data[2]}"
            )
        else:
            await update.message.reply_text("Belum ada data.")
        return

    # ================= PEMASUKAN =================
    if text == "Pemasukan":
        context.user_data["mode"] = "pemasukan_jumlah"
        await update.message.reply_text("Masukkan nominal:")
        return

    if context.user_data.get("mode") == "pemasukan_jumlah":
        jumlah, error = validasi_nominal(text)
        if error:
            await update.message.reply_text(error)
            return
        context.user_data["jumlah"] = jumlah
        context.user_data["mode"] = "pemasukan_tanggal"
        await update.message.reply_text(
            f"Nominal diterima: Rp {jumlah:,}\nMasukkan tanggal YYYY-MM-DD"
        )
        return

    if context.user_data.get("mode") == "pemasukan_tanggal":
        try:
            datetime.strptime(text, "%Y-%m-%d")
            no = generate_no_transaksi("pemasukan", text)
            cursor.execute("""
                INSERT INTO pemasukan (no_transaksi, jumlah, tanggal)
                VALUES (?, ?, ?)
            """, (no, context.user_data["jumlah"], text))
            conn.commit()
            await update.message.reply_text(f"Disimpan ✅\nNo: {no}")
        except:
            await update.message.reply_text("Format tanggal salah.")
        context.user_data["mode"] = None
        return

    # ================= PENGELUARAN =================
    if text == "Pengeluaran":
        context.user_data["mode"] = "pengeluaran_keterangan"
        await update.message.reply_text("Belanja apa?")
        return

    if context.user_data.get("mode") == "pengeluaran_keterangan":
        context.user_data["keterangan"] = text
        context.user_data["mode"] = "pengeluaran_kategori"
        await update.message.reply_text("Kategori?")
        return

    if context.user_data.get("mode") == "pengeluaran_kategori":
        context.user_data["kategori"] = text
        context.user_data["mode"] = "pengeluaran_jumlah"
        await update.message.reply_text("Harga?")
        return

    if context.user_data.get("mode") == "pengeluaran_jumlah":
        jumlah, error = validasi_nominal(text)
        if error:
            await update.message.reply_text(error)
            return
        context.user_data["jumlah"] = jumlah
        context.user_data["mode"] = "pengeluaran_merchant"
        await update.message.reply_text(
            f"Harga diterima: Rp {jumlah:,}\nMerchant?"
        )
        return

    if context.user_data.get("mode") == "pengeluaran_merchant":
        context.user_data["merchant"] = text
        context.user_data["mode"] = "pengeluaran_tanggal"
        await update.message.reply_text("Tanggal YYYY-MM-DD")
        return

    if context.user_data.get("mode") == "pengeluaran_tanggal":
        try:
            datetime.strptime(text, "%Y-%m-%d")
            no = generate_no_transaksi("pengeluaran", text)
            cursor.execute("""
                INSERT INTO pengeluaran
                (no_transaksi, keterangan, kategori, jumlah, merchant, tanggal)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                no,
                context.user_data["keterangan"],
                context.user_data["kategori"],
                context.user_data["jumlah"],
                context.user_data["merchant"],
                text
            ))
            conn.commit()
            await update.message.reply_text(f"Disimpan ✅\nNo: {no}")
        except sqlite3.IntegrityError:
            await update.message.reply_text("Nomor transaksi duplikat.")
        except:
            await update.message.reply_text("Format salah.")
        context.user_data["mode"] = None
        return

    # ================= GRAFIK =================
    if text == "Grafik Kategori":
        bulan = datetime.now().strftime("%Y-%m")
        cursor.execute("""
            SELECT kategori, SUM(jumlah)
            FROM pengeluaran
            WHERE tanggal LIKE ?
            GROUP BY kategori
        """, (f"{bulan}%",))
        data = cursor.fetchall()
        if not data:
            await update.message.reply_text("Belum ada data.")
            return
        kategori = [d[0] for d in data]
        total = [d[1] for d in data]
        plt.figure()
        plt.bar(kategori, total)
        plt.title(f"Pengeluaran per Kategori {bulan}")
        plt.tight_layout()
        plt.savefig("grafik.png")
        plt.close()
        await update.message.reply_photo(photo=open("grafik.png", "rb"))
        os.remove("grafik.png")
        return

    # ================= EXPORT PDF =================
    if text == "Export PDF":
        context.user_data["mode"] = "export_bulan"
        await update.message.reply_text("Masukkan bulan (format YYYY-MM)\nContoh: 2026-02")
        return

    if context.user_data.get("mode") == "export_bulan":
        try:
            datetime.strptime(text, "%Y-%m")
        except:
            await update.message.reply_text("Format salah. Gunakan YYYY-MM")
            return

        bulan = text
        filename = f"Laporan_Keuangan_{bulan}.pdf"
        doc = SimpleDocTemplate(filename, pagesize=pagesizes.A4)
        elements = []
        styles = getSampleStyleSheet()

        elements.append(Paragraph(f"LAPORAN KEUANGAN BULAN {bulan}", styles["Title"]))
        elements.append(Spacer(1, 20))

        cursor.execute("SELECT no_transaksi, jumlah, tanggal FROM pemasukan WHERE tanggal LIKE ?", (f"{bulan}%",))
        pemasukan = cursor.fetchall()

        cursor.execute("""
            SELECT no_transaksi, keterangan, kategori, jumlah, merchant, tanggal
            FROM pengeluaran WHERE tanggal LIKE ?
        """, (f"{bulan}%",))
        pengeluaran = cursor.fetchall()

        total_pm = sum(p[1] for p in pemasukan)
        total_pg = sum(p[3] for p in pengeluaran)
        saldo = total_pm - total_pg

        data_pm = [["No", "Nominal", "Tanggal"]]
        for p in pemasukan:
            data_pm.append([p[0], f"Rp {p[1]:,}", p[2]])

        table_pm = Table(data_pm)
        table_pm.setStyle(TableStyle([("GRID", (0,0), (-1,-1), 1, colors.black)]))
        elements.append(Paragraph("Pemasukan", styles["Heading2"]))
        elements.append(table_pm)
        elements.append(Spacer(1, 20))

        data_pg = [["No", "Belanja", "Kategori", "Harga", "Merchant", "Tanggal"]]
        for p in pengeluaran:
            data_pg.append([p[0], p[1], p[2], f"Rp {p[3]:,}", p[4], p[5]])

        table_pg = Table(data_pg)
        table_pg.setStyle(TableStyle([("GRID", (0,0), (-1,-1), 1, colors.black)]))
        elements.append(Paragraph("Pengeluaran", styles["Heading2"]))
        elements.append(table_pg)
        elements.append(Spacer(1, 20))

        elements.append(Paragraph(f"Total Pemasukan: Rp {total_pm:,}", styles["Normal"]))
        elements.append(Paragraph(f"Total Pengeluaran: Rp {total_pg:,}", styles["Normal"]))
        elements.append(Paragraph(f"Sisa Saldo: Rp {saldo:,}", styles["Normal"]))

        doc.build(elements)
        await update.message.reply_document(open(filename, "rb"))
        os.remove(filename)

        context.user_data["mode"] = None
        return


# ================= RUN =================
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Bot berjalan...")
app.run_polling(drop_pending_updates=True)

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    """Lỗi khi gửi email qua SMTP."""
    pass


def get_smtp_config() -> dict:
    """Đọc cấu hình SMTP từ biến môi trường (không hard-code credentials)."""
    port_str = os.getenv("SMTP_PORT", "587")
    try:
        port = int(port_str)
    except ValueError:
        port = 587

    use_tls_str = os.getenv("SMTP_USE_TLS", "true").lower()
    use_tls = use_tls_str in ("true", "1", "yes")

    use_ssl_str = os.getenv("SMTP_USE_SSL", "false").lower()
    use_ssl = use_ssl_str in ("true", "1", "yes")

    return {
        "host": os.getenv("SMTP_HOST", "localhost"),
        "port": port,
        "username": os.getenv("SMTP_USERNAME", ""),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "from_email": os.getenv("SMTP_FROM_EMAIL", os.getenv("SMTP_USERNAME", "no-reply@ictu.edu.vn")),
        "use_tls": use_tls,
        "use_ssl": use_ssl,
    }


def get_frontend_url() -> str:
    """Lấy địa chỉ Frontend từ biến môi trường FRONTEND_URL."""
    url = os.getenv("FRONTEND_URL", "http://localhost:5173")
    return url.rstrip("/")


def build_reset_password_url(raw_token: str) -> str:
    """Tạo liên kết đặt lại mật khẩu với raw token (SCRUM-48)."""
    frontend_url = get_frontend_url()
    return f"{frontend_url}/reset-password?token={raw_token}"


def build_reset_password_email_content(reset_url: str) -> tuple[str, str, str]:
    """
    Tạo nội dung email đặt lại mật khẩu bằng tiếng Việt:
    - Tiêu đề (Subject)
    - Plain text body
    - HTML body
    Bao gồm liên kết đặt lại, thông báo hết hạn 30 phút và khuyến cáo an toàn.
    """
    subject = "[ICTU] Yêu cầu đặt lại mật khẩu - Hệ thống Quản lý Đào tạo"

    text_body = f"""Xin chào,

Hệ thống Quản lý Đào tạo ICTU đã nhận được yêu cầu đặt lại mật khẩu cho tài khoản của bạn.

Vui lòng truy cập liên kết dưới đây để thực hiện đặt lại mật khẩu:
{reset_url}

LƯU Ý QUAN TRỌNG:
- Liên kết này chỉ có hiệu lực trong vòng 30 phút.
- Mỗi liên kết chỉ được sử dụng duy nhất một lần.
- Nếu bạn không thực hiện yêu cầu này, vui lòng bỏ qua email. Mật khẩu hiện tại của bạn vẫn được giữ nguyên và bảo vệ an toàn.

Trân trọng,
Hệ thống Quản lý Đào tạo ICTU
"""

    html_body = f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Đặt lại mật khẩu</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      line-height: 1.6;
      color: #333333;
      background-color: #f4f6f8;
      margin: 0;
      padding: 0;
    }}
    .email-container {{
      max-width: 600px;
      margin: 30px auto;
      background: #ffffff;
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
      border: 1px solid #e1e4e8;
    }}
    .email-header {{
      background: #1e3a8a;
      color: #ffffff;
      padding: 24px;
      text-align: center;
    }}
    .email-header h1 {{
      margin: 0;
      font-size: 20px;
      font-weight: 600;
    }}
    .email-body {{
      padding: 32px 24px;
    }}
    .btn-reset {{
      display: inline-block;
      background-color: #2563eb;
      color: #ffffff !important;
      padding: 12px 28px;
      font-size: 16px;
      font-weight: 600;
      text-decoration: none;
      border-radius: 6px;
      margin: 20px 0;
    }}
    .note-box {{
      background-color: #eff6ff;
      border-left: 4px solid #2563eb;
      padding: 12px 16px;
      margin: 20px 0;
      font-size: 14px;
      color: #1e40af;
    }}
    .email-footer {{
      background: #f8fafc;
      padding: 16px 24px;
      text-align: center;
      font-size: 12px;
      color: #64748b;
      border-top: 1px solid #e2e8f0;
    }}
  </style>
</head>
<body>
  <div class="email-container">
    <div class="email-header">
      <h1>HỆ THỐNG QUẢN LÝ ĐÀO TẠO ICTU</h1>
    </div>
    <div class="email-body">
      <p>Xin chào,</p>
      <p>Chúng tôi đã nhận được yêu cầu đặt lại mật khẩu cho tài khoản của bạn trên Hệ thống Quản lý Đào tạo ICTU.</p>
      <p style="text-align: center;">
        <a href="{reset_url}" class="btn-reset" target="_blank">Đặt lại mật khẩu</a>
      </p>
      <p style="word-break: break-all; font-size: 13px; color: #64748b;">
        Hoặc sao chép liên kết sau vào trình duyệt: <br>
        <a href="{reset_url}">{reset_url}</a>
      </p>
      <div class="note-box">
        <strong>Lưu ý:</strong>
        <ul>
          <li>Liên kết này sẽ <strong>hết hạn sau 30 phút</strong> kể từ thời điểm gửi.</li>
          <li>Liên kết chỉ có thể sử dụng một lần duy nhất.</li>
          <li>Nếu bạn không yêu cầu đặt lại mật khẩu, vui lòng bỏ qua email này. Mật khẩu của bạn vẫn an toàn.</li>
        </ul>
      </div>
    </div>
    <div class="email-footer">
      <p>Email này được gửi tự động từ Hệ thống Quản lý Đào tạo ICTU. Vui lòng không phản hồi email này.</p>
    </div>
  </div>
</body>
</html>
"""

    return subject, text_body, html_body


def send_email(
    to_email: str,
    subject: str,
    text_content: str,
    html_content: str | None = None,
) -> None:
    """Gửi email qua SMTP client với cấu hình từ biến môi trường."""
    config = get_smtp_config()

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = config["from_email"]
    message["To"] = to_email

    part1 = MIMEText(text_content, "plain", "utf-8")
    message.attach(part1)

    if html_content:
        part2 = MIMEText(html_content, "html", "utf-8")
        message.attach(part2)

    host = config["host"]
    port = config["port"]
    username = config["username"]
    password = config["password"]
    use_tls = config["use_tls"]
    use_ssl = config["use_ssl"]

    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            if use_tls:
                server.starttls()

        if username and password:
            server.login(username, password)

        server.send_message(message)
        server.quit()
    except Exception as error:
        # Ghi log an toàn không bao giờ in raw token hoặc SMTP password
        logger.error(
            "Lỗi khi gửi email SMTP tới %s: %s",
            to_email,
            type(error).__name__,
        )
        raise EmailDeliveryError(f"Không thể gửi email: {type(error).__name__}") from error


def send_password_reset_email(
    to_email: str,
    raw_token: str,
    reset_url: str | None = None,
) -> str:
    """
    Tạo nội dung và gửi email đặt lại mật khẩu tới người dùng (SCRUM-48):
    - Tạo reset URL: {FRONTEND_URL}/reset-password?token=<RAW_TOKEN>
    - Gửi email qua SMTP với thông báo 30 phút và khuyến cáo an toàn.
    - Không log raw token hoặc SMTP credentials.
    - Trả về reset_url được tạo.
    """
    url = reset_url or build_reset_password_url(raw_token)
    subject, text_body, html_body = build_reset_password_email_content(url)

    send_email(
        to_email=to_email,
        subject=subject,
        text_content=text_body,
        html_content=html_body,
    )
    return url

# AgentShield

**Role-based access control middleware for [Hermes Agent](https://github.com/NousResearch/hermes-agent)**

AgentShield biến Hermes thành một agent có thể phục vụ khách hàng bên ngoài — an toàn, có giới hạn, và kiếm được tiền — mà không cần fork hay sửa source code của Hermes.

```
Khách hàng nhắn tin (Telegram/Discord/...)
          ↓
Hermes Gateway
          ↓
AgentShield hook (before_message)
   → Xác định role
   → Kiểm tra rate limit
   → Kiểm tra quyền hành động
          ↓ allow              ↓ deny
Agent xử lý bình thường    Khách nhận message lịch sự
          ↓
AgentShield hook (agent:end)
   → Ghi log cuộc trò chuyện
```

---

## Tính năng

- **RBAC** — phân quyền theo role với allow/deny patterns (`chat`, `skill:*`, `command:*`)
- **Rate limiting** — giới hạn tin nhắn theo phút và theo ngày cho từng role
- **Action inference** — phân biệt `chat`, `command:x`, `skill:x`, `system:reset`, `system:stop`
- **Auto-guest** — người lạ tự động vào role guest, không cần cấu hình whitelist
- **Persistent role assignments** — assign role qua lệnh `/as_assign`, lưu qua restart
- **Conversation logging** — mỗi turn ghi vào `~/.hermes/logs/conversations/<chat_id>.jsonl`
- **Owner alerts** — cảnh báo Telegram khi có hành vi bất thường
- **Zero-fork** — chỉ là một hook file, không cần sửa Hermes

---

## Kiến trúc triển khai

AgentShield được thiết kế cho mô hình **customer-facing agent**:

```
Chủ nhân (Owner)
  → Tương tác với agent qua CLI trực tiếp trên server
  → Toàn quyền, full tools

Khách hàng (Guest)
  → Tương tác qua Telegram/messaging platform
  → Chỉ được chat, rate-limited, không có tools nguy hiểm
```

Hermes config dùng `platform_toolsets.telegram: [safe]` để loại bỏ hoàn toàn
`terminal`, `file`, `process` tool schema — AgentShield chặn ở tầng message,
Hermes config chặn ở tầng tool. Hai lớp độc lập.

---

## Cài đặt

### Yêu cầu
- [Hermes Agent](https://github.com/NousResearch/hermes-agent) đã cài và chạy
- Python 3.9+
- PyYAML (`pip install pyyaml`)

### Bước 1 — Clone repo

```bash
git clone https://github.com/mrqhocungdungai-vn/agentshield
cd agentshield
```

### Bước 2 — Chạy install script

```bash
bash install.sh
```

Script sẽ:
- Copy `hook/handler.py` và `hook/HOOK.yaml` vào `~/.hermes/hooks/agentshield/`
- Tạo file config mẫu tại `~/.hermes/agentshield.yaml` (nếu chưa có)

### Bước 3 — Cấu hình

Chỉnh sửa `~/.hermes/agentshield.yaml`:

```yaml
agentshield:
  enabled: true

  roles:
    guest:
      chat_ids: []
      allow: ["chat"]
      deny: ["command:*", "system:*", "terminal", "skill:*"]
      rate_limit:
        messages_per_minute: 10
        messages_per_day: 200

  messages:
    rate_limit_minute: "Mình đang xử lý khá nhiều tin nhắn, bạn chờ một chút rồi nhắn lại nhé 😊"
    rate_limit_day: "Hôm nay mình đã hỗ trợ bạn khá nhiều rồi. Hẹn gặp lại ngày mai nhé!"
    action_denied: "Tính năng này không khả dụng trong kênh chat. Vui lòng liên hệ nhân viên hỗ trợ nhé 😊"
```

### Bước 4 — Cấu hình Hermes

Trong `~/.hermes/config.yaml`, đổi toolset Telegram sang `safe` để loại bỏ tools nguy hiểm:

```yaml
platform_toolsets:
  telegram:
    - safe    # web + vision only, không có terminal/file/process
```

Và cho phép mọi user Telegram đi qua (AgentShield sẽ tự kiểm soát):

```bash
# Thêm vào ~/.hermes/.env
TELEGRAM_ALLOW_ALL_USERS=true
```

### Bước 5 — Restart gateway

```bash
hermes gateway restart
```

Kiểm tra hook đã load:

```bash
journalctl --user -u hermes-gateway -n 20 | grep agentshield
# Kết quả mong đợi:
# [hooks] Loaded hook 'agentshield' for events: ['before_message', 'agent:end']
```

---

## Cấu hình đầy đủ

Xem [`config/agentshield.yaml.example`](config/agentshield.yaml.example) để có ví dụ đầy đủ với nhiều role.

### Role system

| Role | Mô tả |
|------|-------|
| `owner` | Bypass mọi check, có thể dùng `/as_*` admin commands |
| `admin` | Full quyền, rate limit cao |
| `user` | Chat + skill + một số lệnh an toàn |
| `guest` | Chỉ chat, rate limit thấp — default cho người lạ |

Người lạ (unlisted) tự động vào role `guest`. Không cần cấu hình whitelist.

### Action types

| Action | Khi nào |
|--------|---------|
| `chat` | Tin nhắn thường |
| `command:<name>` | Slash command (VD: `/help` → `command:help`) |
| `skill:<name>` | Chạy skill (VD: `/skill run summarize`) |
| `system:reset` | `/reset`, `/new`, `/clear` |
| `system:stop` | `/stop`, `/cancel` |

---

## Admin commands (nếu dùng owner role)

Gửi từ Telegram account có `owner_chat_id`:

| Lệnh | Mô tả |
|------|-------|
| `/as_assign <chat_id> <role>` | Assign role động (lưu qua restart) |
| `/as_revoke <chat_id>` | Xóa dynamic assignment |
| `/as_roles` | Xem tất cả dynamic assignments |
| `/as_info <chat_id>` | Xem role + rate state của user |

---

## Chạy tests

```bash
pip install pytest pytest-asyncio pyyaml
pytest tests/ -v
```

---

## Mục tiêu dự án

> Biến Hermes Agent thành một **nhân viên AI có thể kiếm tiền** phục vụ khách hàng thực tế — tư vấn, chăm sóc, hỗ trợ 24/7 — trong khi vẫn giữ an toàn tuyệt đối cho hệ thống bên trong.

AgentShield là lớp giáp bảo vệ để agent có thể "ra ngoài làm việc" mà chủ nhân không lo bị khai thác.

---

## Liên hệ & theo dõi

Dự án được chia sẻ công khai để cộng đồng tham khảo và đóng góp.

- **TikTok:** [@mr.q.hoc.ung.dung.ai](https://www.tiktok.com/@mr.q.hoc.ung.dung.ai)
- **GitHub:** [mrqhocungdungai-vn/agentshield](https://github.com/mrqhocungdungai-vn/agentshield)

---

## Đóng góp

Pull requests và issues luôn được chào đón.

---

> ⚠️ **Lưu ý từ tác giả**
>
> Repo này được xây dựng bởi **Hermes Agent** — dưới sự điều phối của một kỹ sư ICT không chuyên về lập trình.
> Mục tiêu là thực tế và học hỏi, không phải production-perfect.
>
> Chắc chắn còn nhiều vấn đề cần cải thiện — về security, performance, edge cases, và code quality.
> Nếu bạn là developer và thấy điều gì cần fix hoặc làm tốt hơn, **issues và PRs luôn được chào đón**.
>
> Cùng nhau xây dựng một công cụ để AI agent có thể làm việc thực sự — an toàn, hiệu quả, và sinh ra giá trị.

---

## License

MIT

# ⚜ Celesteria

**A polished medieval kingdom living inside Discord.**

Celesteria is a custom Discord bot that brings the atmosphere of a royal realm to your server — elegant embeds, moderation, community progression, and a cohesive medieval-fantasy identity.

*by sunflower1y*

---

## Setup

### Prerequisites

- Python 3.12 or newer
- A Discord Bot Token ([Developer Portal](https://discord.com/developers/applications))
- **Message Content Intent** enabled in the Developer Portal

### Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd celesteria/bot

# Create virtual environment
py -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS

# Install dependencies
pip install -r requirements.txt

# Create your environment file
copy .env.example .env        # Windows
# cp .env.example .env        # Linux/macOS
```

### Configuration

Edit `.env` and add your Discord bot token:

```ini
DISCORD_TOKEN=your_token_here
```

For faster slash command sync during development, add your test server's ID:

```ini
TEST_GUILD_ID=123456789012345678
```

### Running

```bash
py main.py
```

---

## Commands

All commands are available as both **slash commands** and **prefix commands** (`!c`).

### Core Commands
| Command | Description |
|---|---|
| `/ping` · `!cping` | Check bot latency and status |
| `/help` · `!chelp` | Interactive command browser |
| `/userinfo` · `!cuserinfo` | View member information |

### Moderation Decrees
| Command | Description |
|---|---|
| `/warn` · `!cwarn` | Issue a formal warning recorded in royal chronicles |
| `/kick` · `!ckick` | Banish a member from the realm |
| `/ban` · `!cban` | Permanently exile a member or user (with confirmation prompt) |
| `/timeout` · `!ctimeout` | Temporarily silence a member (e.g. `10m`, `2h`, `1d`) |
| `/clear` · `!cclear` | Purge 1 to 100 messages from the channel scroll |
| `/cases` · `!ccases` | Inspect decree chronicles for a member or specific case ID |
| `/setmodlog` · `!csetmodlog` | Configure or unbind the moderation logging channel |

---

## Project Structure

```
bot/
├── main.py              # Entry point
├── bot/                  # Bot initialization
│   ├── celesteria.py     # Bot subclass
│   └── config.py         # Configuration
├── cogs/                 # Command modules
│   ├── core.py           # Core commands
│   └── moderation.py     # Moderation decrees
├── db/                   # Database layer
│   ├── database.py       # SQLite connection manager
│   └── repository.py     # Moderation cases & config data access
├── services/             # Domain service layer
│   └── moderation.py     # Moderation orchestrator & Discord execution
├── ui/                   # Visual components
│   ├── theme.py          # Design tokens
│   ├── embeds.py         # Embed builders
│   ├── formatters.py     # Text formatting
│   └── views.py          # Buttons & menus (HelpView, ConfirmView)
└── utils/                # Utilities
    ├── duration.py       # Duration parser & formatter
    ├── errors.py         # Error handling
    ├── logger.py         # Logging setup
    └── permissions.py    # Permission & role hierarchy checks
```

---

## Security

- Bot token is stored in `.env` (git-ignored)
- Never hardcode secrets in source code
- If a token is ever accidentally committed, **rotate it immediately** via the Discord Developer Portal

---

## License

Private project. All rights reserved.

*Celesteria · by sunflower1y*


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
- **Server Members Intent** enabled in the Developer Portal

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

# Create your environment file from template
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

### Running Tests

```bash
py -m unittest discover tests
```

---

## Commands

All commands are available as both **slash commands** (`/`) and **prefix commands** (`!c`).

### ✦ Core Commands
| Command | Description |
|---|---|
| `/ping` · `!cping` | Check bot latency, uptime, and system status |
| `/help` · `!chelp` | Interactive command codex with category selection |
| `/userinfo` · `!cuserinfo` | View detailed member information, badges, and roles |

### ⚔ Moderation Decrees
| Command | Description |
|---|---|
| `/warn` · `!cwarn` | Issue a formal warning recorded in the royal chronicles |
| `/kick` · `!ckick` | Banish a member from the realm |
| `/ban` · `!cban` | Permanently exile a member or user (with confirmation prompt) |
| `/timeout` · `!ctimeout` | Temporarily silence a member (e.g. `10m`, `2h`, `1d`) |
| `/clear` · `!cclear` | Purge 1 to 100 messages from the channel scroll |
| `/cases` · `!ccases` | Inspect decree chronicles for a member or specific case ID |
| `/setmodlog` · `!csetmodlog` | Configure or unbind the moderation logging channel |

### 🏰 Server Administration & Control
| Command | Description |
|---|---|
| `/config` · `!cconfig` | Open the interactive Royal Realm Configuration dashboard |
| `/serverconfig` · `!cserverconfig` | Display current server configuration and channel bindings |
| `/setwelcome` · `!csetwelcome` | Configure or disable welcome announcements and greetings |
| `/testwelcome` · `!ctestwelcome` | Preview the welcome announcement embed |
| `/setcounter` · `!csetcounter` | Configure dynamic member counter channel and display template |
| `/setserverlog` · `!csetserverlog` | Configure or unbind the server activity audit channel |
| `/toggleveling` · `!ctoggleveling` | Toggle chat leveling progression on or off for the realm |

### ⚜ Social Renown & Progression
| Command | Description |
|---|---|
| `/level` · `!clevel` | Inspect member level, XP progress bar, and server rank |
| `/profile` · `!cprofile` | Display full royal character profile with Celesteria honors |
| `/leaderboard` · `!cleaderboard` | Paginated Royal Hall of Fame ranking top citizens |
| `/levelrewards` · `!clevelrewards` | Inspect configured role rewards for level progression |
| `/setlevelreward` · `!csetlevelreward` | Assign a Discord role as a reward for attaining a level tier |
| `/removelevelreward` · `!cremovelevelreward` | Revoke a configured role reward for a level tier |
| `/setlevelupchannel` · `!csetlevelupchannel` | Direct or mute level advancement celebrations |

---

## Project Structure

```
bot/
├── main.py                  # Entry point
├── .env.example             # Configuration template
├── bot/                     # Bot initialization
│   ├── celesteria.py        # Bot subclass & lifecycle management
│   └── config.py            # Environment configuration
├── cogs/                    # Command presentation layer
│   ├── core.py              # Core commands & slash sync
│   ├── moderation.py        # Moderation decrees
│   ├── server.py            # Server administration, /config, & events
│   └── leveling.py          # Leveling, profiles, & role rewards
├── db/                      # Data access layer
│   ├── database.py          # SQLite connection manager & WAL pragmas
│   ├── repository.py        # Moderation cases data access
│   ├── server_repository.py # Server configuration data access & cache
│   └── level_repository.py  # Member XP, ranks, & level rewards
├── services/                # Domain business logic layer
│   ├── moderation.py        # Moderation decrees & hierarchy orchestration
│   ├── server.py            # Welcome, counter rename rate-limiting, & logs
│   └── leveling.py          # Progression math, anti-spam heuristics, & rewards
├── ui/                      # Visual design system
│   ├── theme.py             # Palette tokens & iconography
│   ├── embeds.py            # CelesteriaEmbed factory methods
│   ├── formatters.py        # Time, numbers, and progress bar formatters
│   └── views.py             # HelpView, ConfirmView, Pagination, & ConfigDashboardView
├── utils/                   # Utilities
│   ├── duration.py          # Duration string parser & formatter
│   ├── errors.py            # Unified global error handler & error IDs
│   ├── logger.py            # Structured logging & secret masking filter
│   └── permissions.py       # Permission & role hierarchy validators
└── tests/                   # Test suite
    ├── test_moderation_commands.py
    ├── test_phase2.py
    ├── test_phase3.py
    ├── test_phase4.py
    └── test_phase5.py
```

---

## Security

- Bot token is stored in `.env` (git-ignored)
- `.env.example` contains only sanitized placeholders
- Logging system actively redacts bot tokens and sensitive values
- Parameterized SQLite queries across all repositories (SQL injection immune)
- Strict role hierarchy and Discord permission validation across all commands
- Error handler logs detailed tracebacks internally with error IDs, never exposing stack traces or internals to users

---

## License

Private project. All rights reserved.

*Celesteria · by sunflower1y*

# DeFi Position Calculator Bot - Railway Deployment

## 🚀 Quick Deploy to Railway

### Option 1: Deploy from GitHub

1. **Push code to GitHub:**
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin YOUR_REPO_URL
git push -u origin main
```

2. **Deploy on Railway:**
   - Go to [railway.app](https://railway.app)
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Choose your repository
   - Railway will auto-detect Python and deploy

3. **Set Environment Variables:**
   - Go to your project settings
   - Add variables:
     ```
     BOT_TOKEN=your_telegram_bot_token
     CRYPTORANK_API_KEY=your_cryptorank_api_key (optional)
     ```

### Option 2: Deploy from CLI

1. **Install Railway CLI:**
```bash
npm install -g @railway/cli
```

2. **Login:**
```bash
railway login
```

3. **Initialize and deploy:**
```bash
railway init
railway up
```

4. **Set environment variables:**
```bash
railway variables set BOT_TOKEN=your_token
railway variables set CRYPTORANK_API_KEY=your_key
```

## 📁 Required Files

```
your-project/
├── defi_bot_railway.py    # Main bot file
├── requirements.txt       # Python dependencies
├── Procfile              # Railway start command
├── railway.json          # Railway configuration
└── README.md            # This file
```

## ⚙️ Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | ✅ Yes | Telegram bot token from @BotFather |
| `CRYPTORANK_API_KEY` | ❌ No | CryptoRank API key (optional) |

## 🔧 Configuration

### Python Version
- Python 3.11+ (auto-detected by Railway)

### Dependencies
```
aiogram==3.15.0
aiohttp==3.11.11
python-dotenv==1.0.1
```

### Start Command
```bash
python defi_bot_railway.py
```

## 📊 Bot Features

✅ **Price Sources:**
- CryptoRank API (if configured)
- CoinGecko API (20+ coins)
- Manual input (any token)

✅ **Calculations:**
- Health Factor
- Liquidation Price
- Maximum Borrow
- Price Drop Scenarios

✅ **Modes:**
- Calculate by LTV
- Calculate by borrow amount

## 🐛 Troubleshooting

### Bot not starting?

**Check logs:**
```bash
railway logs
```

**Common issues:**

1. **Missing BOT_TOKEN:**
   ```
   Error: BOT_TOKEN not set in environment variables
   ```
   Solution: Add BOT_TOKEN in Railway dashboard

2. **Wrong Python version:**
   Railway auto-detects Python from requirements.txt
   
3. **Dependencies not installing:**
   Check requirements.txt format

### Bot stops after deployment?

**Check health:**
```bash
railway status
```

**Restart service:**
```bash
railway restart
```

## 📝 Logs

**View live logs:**
```bash
railway logs --tail
```

**Example successful startup:**
```
==================================================
🚀 DeFi Calculator Bot Starting
✅ Bot: @your_bot_name
✅ CryptoRank API configured
==================================================
```

## 🔄 Updates

**Deploy new version:**
```bash
git add .
git commit -m "Update bot"
git push
```

Railway will automatically redeploy.

**Or via CLI:**
```bash
railway up
```

## 💰 Railway Pricing

**Free Tier:**
- $5 credit/month
- ~500 hours runtime
- Enough for 24/7 bot operation

**Pro Plan:**
- $20/month
- More resources
- Priority support

## 🛡️ Security

**Best practices:**
- Never commit `.env` file
- Use Railway environment variables
- Rotate API keys regularly
- Monitor bot logs

## 📞 Support

**Bot Commands:**
- `/start` - Start calculation
- `/reset` - Reset current calculation
- `/help` - Show help

**Railway Support:**
- [Documentation](https://docs.railway.app)
- [Discord](https://discord.gg/railway)
- [GitHub Issues](https://github.com/railwayapp/railway)

## 📄 License

MIT License - Free to use and modify

---

**Made with ❤️ for DeFi community**

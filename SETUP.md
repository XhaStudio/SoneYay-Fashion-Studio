TELEGRAM FASHION SHOP (Python version) — SETUP
================================================

1. RUNTIME
   - Python 3.10+
   - (Recommended) create a virtual env:
       python -m venv venv
       venv\Scripts\activate      (Windows)
       source venv/bin/activate   (macOS/Linux)
   - Install dependencies:
       pip install -r requirements.txt
   - Run:
       python server.py

2. .env FILE
   - Copy .env.example to .env and fill in every value:
       PORT=3000
       BOT_TOKEN=            <- from @BotFather
       WEBAPP_URL=           <- printed by ngrok on startup, or your real host URL
       NGROK_AUTHTOKEN=      <- from https://dashboard.ngrok.com
       ADMIN_CHAT_ID=        <- send /whoami to your bot to get this
       KBZPAY_NAME=
       KBZPAY_NUMBER=
       WAVEPAY_NAME=
       WAVEPAY_NUMBER=

3. WHAT CHANGED FROM THE NODE VERSION
   - Same behavior, rewritten in Flask + pyTelegramBotAPI + pyngrok.
   - Customers can now upload the payment screenshot directly inside the
     WebApp (click the box or drag-and-drop an image) instead of having
     to switch to the bot chat. Sending it in the chat still works too,
     as a fallback.
   - Orders are still stored in orders.json (git-ignored). Uploaded
     screenshots are saved to the uploads/ folder (also git-ignored).

4. IF THE BOT CAN'T REACH TELEGRAM
   - This happens on networks/machines where api.telegram.org is blocked
     (some ISPs, some locked-down Windows environments, some corporate
     networks). Test with:
       curl -v https://api.telegram.org
     If that fails too, it's a network/firewall issue, not the code —
     you'll need a VPN/proxy or a different network.

5. SECURITY REMINDER
   - Never paste your real BOT_TOKEN, NGROK_AUTHTOKEN, or ADMIN_CHAT_ID
     into a chat, ticket, or public repo. If one leaks, revoke/regenerate
     it immediately (BotFather: /revoke for the bot token; ngrok
     dashboard for the authtoken).

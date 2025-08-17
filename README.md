# Kick OAuth Flow Demo

A Flask web application that demonstrates OAuth 2.0 authentication with Kick.com, featuring live chat, channel search, and message sending capabilities.

## Features

- 🔐 **OAuth 2.0 Authentication** with PKCE (Proof Key for Code Exchange)
- 🔍 **Channel Search** by slug with autocomplete suggestions
- 💬 **Live Chat** - view and send messages in real-time
- 📱 **Responsive UI** with modern design
- 🔄 **Token Refresh** - automatic token renewal
- 🚀 **Railway Ready** - easy deployment configuration

## Live Demo

Visit the live demo: [Your Railway URL here]

## Setup

### Prerequisites

- Python 3.8+
- Kick.com OAuth App credentials
- Railway account (for deployment)

### Local Development

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/kickOauthFlow.git
   cd kickOauthFlow
   ```

2. **Create virtual environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment variables**
   Create a `.env` file:
   ```env
   KICK_CLIENT_ID=your_client_id
   KICK_CLIENT_SECRET=your_client_secret
   KICK_REDIRECT_URI=http://127.0.0.1:8000/callback
   KICK_SCOPES=user:read channel:read chat:write
   FLASK_SECRET_KEY=your_secret_key
   ```

5. **Run the application**
   ```bash
   python app.py
   ```

6. **Open your browser**
   Navigate to `http://127.0.0.1:8000`

## OAuth Setup

1. Go to [Kick.com Developer Portal](https://dev.kick.com/)
2. Create a new OAuth application
3. Set redirect URI to match your setup
4. Copy Client ID and Client Secret to your `.env` file

## API Endpoints

- `GET /` - Home page with login
- `GET /login` - Initiate OAuth flow
- `GET /callback` - OAuth callback handler
- `GET /me` - User profile (requires auth)
- `GET /channels/search` - Search channels by slug
- `GET /live-chat` - Live chat interface
- `POST /send-chat` - Send chat messages
- `GET /channels/suggest` - Channel autocomplete

## Live Chat Features

- **Real-time messaging** via Pusher WebSocket
- **Channel joining** by slug
- **Message sending** with OAuth authentication
- **Auto-scroll** chat interface
- **Error handling** and status messages

## Deployment on Railway

1. **Connect GitHub repository** to Railway
2. **Set environment variables** in Railway dashboard
3. **Update KICK_REDIRECT_URI** to your Railway domain
4. **Deploy automatically** on git push

### Railway Environment Variables
```env
KICK_CLIENT_ID=your_client_id
KICK_CLIENT_SECRET=your_client_secret
KICK_REDIRECT_URI=https://your-app.up.railway.app/callback
KICK_SCOPES=user:read channel:read chat:write
FLASK_SECRET_KEY=your_secret_key
```

## Security Features

- **PKCE** for enhanced OAuth security
- **State parameter** validation
- **Secure cookies** on HTTPS
- **Session management** with Flask
- **Token refresh** before expiration

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

This project is open source and available under the [MIT License](LICENSE).

## Support

If you encounter any issues:
1. Check the [Issues](https://github.com/yourusername/kickOauthFlow/issues) page
2. Create a new issue with detailed information
3. Include your environment and error logs

## Acknowledgments

- Built with [Flask](https://flask.palletsprojects.com/)
- OAuth integration with [Kick.com API](https://dev.kick.com/)
- Real-time chat via [Pusher](https://pusher.com/)
- Deployed on [Railway](https://railway.app/)

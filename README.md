# Playto Payout Engine

A minimal payout engine for Playto Pay - cross-border payment infrastructure for Indian agencies and freelancers.

## Tech Stack

- **Backend**: Django 4.2 + Django REST Framework
- **Database**: PostgreSQL
- **Background Jobs**: Django-Q
- **Frontend**: React + Tailwind CSS

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Node.js 18+

### Backend Setup

```bash
# Create virtual environment
cd playto-payout-engine
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Seed test data
python manage.py seed_data

# Run server
python manage.py runserver
```

### Frontend Setup

```bash
# Install dependencies
cd frontend
npm install

# Run development server
npm run dev
```

## API Endpoints

| Method | Endpoint | Description |
|--------|-----------|-------------|
| POST | /api/v1/payouts | Create payout request |
| GET | /api/v1/payouts | List merchant payouts |
| GET | /api/v1/merchants/{id}/balance | Get merchant balance |
| GET | /api/v1/merchants/{id}/ledger | Get ledger entries |

## Environment Variables

```
DATABASE_URL=postgresql://user:pass@localhost:5432/playto
DJANGO_SECRET_KEY=your-secret-key
DEBUG=True
```

## Core Features

- **Merchant Ledger**: Balance in paise (BigInteger), derived from credits/debits
- **Payout Request API**: Idempotency key support, state machine lifecycle
- **Background Worker**: Process payouts with 70% success, 20% fail, 10% hang
- **Concurrency Handling**: Database-level locking to prevent overdraws
- **Retry Logic**: Exponential backoff, max 3 attempts

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   React     │────▶│   Django    │────▶│ PostgreSQL  │
│   Frontend  │     │   REST API   │     │             │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                    ┌──────┴──────┐
                    │  Django-Q   │
                    │   Worker    │
                    └─────────────┘
```

## License

MIT
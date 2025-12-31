# Mini ERP System

A lightweight Enterprise Resource Planning (ERP) system built with Flask for managing inventory, suppliers, and transactions with AI-powered reorder suggestions.

## Features

- **Product Management**: Add, edit, delete, and track products with SKU and stock levels
- **Supplier Management**: Manage supplier information and relationships
- **Transaction Tracking**: Record purchases and sales with automatic stock updates
- **Dashboard Analytics**: Real-time inventory overview and low stock alerts
- **Reports & Charts**: Visual analytics for sales trends, profit analysis, and top products
- **AI Reorder Suggestions**: Smart inventory reordering using Together AI integration

## Tech Stack

- **Backend**: Flask (Python)
- **Database**: SQLite
- **Frontend**: HTML, CSS, Bootstrap
- **AI Integration**: Together AI (Llama-3.3-70B-Instruct-Turbo-Free)
- **Charts**: Chart.js

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd erp1
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up Together AI API key:
   - Get your API key from [Together AI](https://together.ai)
   - Add it to the `suggest_reorder_quantity_from_ai` function in `app.py`

4. Run the application:
```bash
python app.py
```

5. Access the application at `http://localhost:5000`

## Database Schema

### Supplier Table
- `id`: Primary key
- `name`: Supplier name (unique)
- `contact_email`: Contact email
- `created_at`, `updated_at`: Timestamps

### Product Table
- `id`: Primary key
- `name`: Product name
- `sku`: Stock Keeping Unit (unique)
- `stock_quantity`: Current inventory level
- `unit_price`: Price per unit
- `supplier_id`: Foreign key to Supplier
- `created_at`, `updated_at`: Timestamps

### Transaction Table
- `id`: Primary key
- `product_id`: Foreign key to Product
- `quantity`: Transaction quantity
- `type`: 'purchase' or 'sale'
- `date`: Transaction date
- `unit_price`: Price at transaction time

## Key Features

### Dashboard
- Total products and inventory value
- Low stock alerts (< 10 units)
- Transaction summary

### Product Management
- CRUD operations for products
- Stock level tracking
- Supplier associations

### Transaction Management
- Record purchases and sales
- Automatic stock updates
- Transaction history with filtering

### Reports & Analytics
- Sales trends over time
- Net profit analysis
- Top-selling products
- Transaction type distribution

### AI-Powered Reorder Suggestions
- Analyzes 30-day transaction history
- Considers lead times and safety stock
- Provides intelligent reorder quantities with reasoning

## API Endpoints

- `GET /api/suggest_reorder/<product_id>`: Get AI-powered reorder suggestion

## Usage

1. **Add Suppliers**: Start by adding suppliers in the Suppliers section
2. **Add Products**: Create products and associate them with suppliers
3. **Record Transactions**: Log purchases to increase stock, sales to decrease stock
4. **Monitor Dashboard**: Track inventory levels and low stock alerts
5. **View Reports**: Analyze business performance with charts and metrics
6. **Get AI Suggestions**: Use the reorder feature for intelligent inventory management

## File Structure

```
erp1/
├── app.py              # Main Flask application
├── models.py           # Database models (empty - using inline SQL)
├── config.py           # Configuration settings (empty)
├── utils.py            # Utility functions (empty)
├── requirements.txt    # Python dependencies
├── database.db         # SQLite database (auto-generated)
├── templates/          # HTML templates
│   ├── base.html
│   ├── dashboard.html
│   ├── products.html
│   ├── suppliers.html
│   ├── transactions.html
│   ├── reports.html
│   ├── edit_product.html
│   └── edit_transaction.html
└── README.md
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is open source and available under the [MIT License](LICENSE).

## Notes

- This is a prototype/educational project
- For production use, consider adding authentication, input validation, and environment variables for API keys
- The Together AI integration requires an active API key
- Database is automatically initialized on first run
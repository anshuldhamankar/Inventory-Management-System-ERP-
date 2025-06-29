import sqlite3
from flask import Flask,render_template, request,redirect,url_for,flash, g,jsonify
from datetime import datetime, timedelta
import os
import json # added json for parsing ai response
from together import Together

app =Flask(__name__)
app.secret_key='ERP'

# --- DB Configuration ---

DATABASE = 'database.db'

"""connects to existing db  / Cretes new"""
def get_db():
    db=getattr(g,'_database',None)
    if db is None:
        db =sqlite3.connect(DATABASE)
        db.row_factory= sqlite3.Row
    return db

"""disconnects from the db at the end of the request"""
@app.teardown_appcontext
def close_connection(exception):
    db =getattr(g,'_database', None)
    if db is not None:
        db.close()

"""initialize the db schema."""
def init_db():
    with app.app_context():
        db =get_db()
        cursor=db.cursor()
        # create supplier table if it does not exist
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS Supplier (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                contact_email TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # create product table if it does not exist
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS Product (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                sku TEXT NOT NULL UNIQUE,
                stock_quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                supplier_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (supplier_id) REFERENCES Supplier (id) ON DELETE SET NULL
            )
        ''')
        # create transaction table if not exists
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS "Transaction" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('purchase', 'sale')),
                date TEXT NOT NULL, -- Stored as replete-MM-DD
                unit_price REAL NOT NULL,
                FOREIGN KEY (product_id) REFERENCES Product (id) ON DELETE CASCADE
            )
        ''')
        db.commit()
        print("Database initialized successfully.")


# --- Helper Functions for Database Operations ---
# These must be defined BEFORE the routes that use them

"""fetches all products with their supplier names and converts date strings to datetime objects."""
def get_all_products():

    db =get_db()
    products_raw= db.execute('''
        SELECT p.*, s.name AS supplier_name
        FROM Product p
        LEFT JOIN Supplier s ON p.supplier_id = s.id
        ORDER BY p.name
    ''').fetchall()

    # convert 'created_at' and 'updated_at' strings to datetime tyope
    products_list= []
    for product in products_raw:
        product_dict= dict(product)
        if product_dict['created_at']:
            # SQLite stores TIMESTAMP as 'YYYY-MM-DD HH:MM:%S'
            product_dict['created_at'] =datetime.strptime(product_dict['created_at'],'%Y-%m-%d %H:%M:%S')
        if product_dict['updated_at']:
            product_dict['updated_at']=datetime.strptime(product_dict['updated_at'],'%Y-%m-%d %H:%M:%S')
        products_list.append(product_dict)
    return products_list

"""load a single product by ID."""
def get_product_by_id(product_id):
    db= get_db()
    product =db.execute('SELECT * FROM Product WHERE id = ?',(product_id,)).fetchone()
    # if a product exists... convert its date strings to datetime objects
    if product:
        product_dict= dict(product)
        if product_dict['created_at']:
            product_dict['created_at'] =datetime.strptime(product_dict['created_at'], '%Y-%m-%d %H:%M:%S')
        if product_dict['updated_at']:
            product_dict['updated_at']=datetime.strptime(product_dict['updated_at'],'%Y-%m-%d %H:%M:%S')
        return product_dict
    return None


"""fetch all suppliers and counts products associated with each."""
def get_all_suppliers():
    db=get_db()
    suppliers= db.execute('''
        SELECT s.*, COUNT(p.id) AS product_count
        FROM Supplier s
        LEFT JOIN Product p ON s.id = p.supplier_id
        GROUP BY s.id
        ORDER BY s.name
    ''').fetchall()
    return suppliers


"""fetches a single supplier by ID."""
def get_supplier_by_id(supplier_id):
    db=get_db()
    supplier=db.execute('SELECT * FROM Supplier WHERE id = ?',(supplier_id,)).fetchone()
    return supplier

"""fetche all transactions with product names and converts date strings to datetime objects"""
def get_all_transactions():
    db = get_db()
    transactions_raw = db.execute('''
        SELECT t.*, p.name AS product_name, p.sku AS product_sku, p.unit_price AS product_current_price
        FROM "Transaction" t
        JOIN Product p ON t.product_id = p.id
        ORDER BY t.date DESC, t.id DESC
    ''').fetchall()

    transactions_list = []
    for txn in transactions_raw:
        txn_dict= dict(txn)
        if txn_dict['date']:
            txn_dict['date']=datetime.strptime(txn_dict['date'],'%Y-%m-%d')
        transactions_list.append (txn_dict)
    return transactions_list

"""fetches a single transaction by ID...including product details."""
def get_transaction_by_id(transaction_id):
    db =get_db()
    txn=db.execute('''
        SELECT t.*, p.name AS product_name, p.sku AS product_sku, p.stock_quantity AS current_product_stock
        FROM "Transaction" t
        JOIN Product p ON t.product_id = p.id
        WHERE t.id = ?
    ''', (transaction_id,)).fetchone()
    if txn:
        txn_dict =dict(txn)
        if txn_dict['date']:
            txn_dict['date']=datetime.strptime(txn_dict['date'],'%Y-%m-%d')
        return txn_dict
    return None


# ---BONUS POINT Im integrating TogetherAI API as some modles are free on it ive used it because i had a good experience with it in my personal projects ---
def suggest_reorder_quantity_from_ai(product_id):

    db =get_db()
    product= get_product_by_id(product_id)

    if not product:
        return {"error": "Product not found."}, 404

    # calculate sales/purchases for the last 30 days
    thirty_days_ago =(datetime.now()-timedelta(days=30)).strftime('%Y-%m-%d')
    transactions_30_days_raw =db.execute('''
        SELECT type, SUM(quantity) as total_quantity
        FROM "Transaction"
        WHERE product_id = ? AND date >= ?
        GROUP BY type
    ''', (product_id,thirty_days_ago)).fetchall()

    total_sales_30_days=0
    total_purchases_30_days=0
    for txn in transactions_30_days_raw:
        if txn['type']=='sale':
            total_sales_30_days+= txn['total_quantity']
        elif txn['type'] =='purchase':
            total_purchases_30_days+=txn['total_quantity']

    prompt_text = (
        f"suggest an optimal reorder quantity for {product['name']} (SKU: {product['sku']}). " # we target the product using 'sku'
        f"current stock: {product['stock_quantity']} units. "
        f"transaction history for the last 30 days: {total_sales_30_days} units sold, "
        f"{total_purchases_30_days} units purchased. "
        "consider a typical lead time of 7 days and aim to maintain stock for approximately 30 days of sales. "
        "output your suggestion strictly as a JSON object with two keys: 'reorder_quantity' (integer) and 'reasoning' (string)."
        "for example: {'reorder_quantity': 100, 'reasoning': 'Based on average sales and safety stock.'}"
    )

#as of now we arent taking this protoype to a production level so i believe its okay to hardcode the api key here or else we could have stored it in env variable
    client = Together(api_key="b2f7ed331ce942ac3ea07770028567119033ff1151df0fc623ef022a580b2c96")
    try:
        response = client.chat.completions.create(
            model="meta-llama/Llama-3.3-70B-Instruct-Turbo-Free", # Specified model
            messages=[
                {
                    "role": "user",
                    "content": prompt_text
                }
            ],
            response_format={"type": "json_object"}
        )

        if response.choices and response.choices[0].message and response.choices[0].message.content is not None:
            ai_response_content=response.choices[0].message.content
            print(f"DEBUG: Raw AI Response Content: '{ai_response_content}'")

            if not ai_response_content.strip(): # Check if content is empty or just whitespace
                return {"error": "AI returned an empty response."}, 500

            try:
                ai_data=json.loads(ai_response_content)
                reorder_qty=ai_data.get('reorder_quantity')
                reasoning=ai_data.get('reasoning', 'No specific reasoning provided.')

                if isinstance(reorder_qty, int) and reorder_qty >= 0:
                    return {"reorder_quantity": reorder_qty, "reasoning": reasoning}, 200
                else:
                    return {"error": "AI returned an invalid reorder quantity format or value."}, 500
            except json.JSONDecodeError as e:
                # This block will now catch the "Expecting value" error
                print(f"ERROR: JSON Decode Error: {e} with raw content: '{ai_response_content}'")
                return {"error": f"Failed to parse AI response as JSON: {e}. Raw response: {ai_response_content}"}, 500
        else:
            return {"error": "Unexpected Together AI response format or missing content."}, 500

    except Exception as e:
        print(f"An error occurred during Together AI integration: {e}")
        return {"error": f"Failed to get AI suggestion from Together API: {e}"}, 500


# --- Routes ---

@app.route('/')
@app.route('/dashboard')
def dashboard():
    """if available stock of x product < 10 then add x in low_stoc_products."""
    db=get_db()

    total_products=db.execute('SELECT COUNT(*) FROM Product').fetchone()[0]

    total_value_row=db.execute('SELECT SUM(stock_quantity * unit_price) FROM Product').fetchone()
    total_value= round(total_value_row[0] if total_value_row[0] is not None else 0, 2)

    low_stock_products =db.execute('''
        SELECT p.*, s.name AS supplier_name
        FROM Product p
        LEFT JOIN Supplier s ON p.supplier_id = s.id
        WHERE p.stock_quantity < 10
        ORDER BY p.stock_quantity ASC
    ''').fetchall()
    low_stock_count= len(low_stock_products)

    total_transactions=db.execute('SELECT COUNT(*) FROM "Transaction"').fetchone()[0]

    return render_template('dashboard.html',
                           total_products=total_products,
                           total_value=total_value,
                           low_stock_products=low_stock_products,
                           low_stock_count=low_stock_count,
                           total_transactions=total_transactions)

@app.route('/products')
def products():
    """display the product list and a form for adding products"""
    products_list=get_all_products()
    suppliers_list=get_all_suppliers()
    return render_template('products.html', products=products_list,suppliers=suppliers_list)

@app.route('/add_product',methods=['POST'])
def add_product():
    """logic for adding a product."""
    name=request.form['name']
    sku=request.form['sku']
    try:
        unit_price=float(request.form['unit_price'])
        stock_quantity=int(request.form['stock_quantity'])
        supplier_id=int(request.form['supplier_id'])
    except ValueError:
        flash('Invalid input for price, quantity, or supplier. Please ensure they are numbers.', 'danger')
        return redirect(url_for('products'))

    if unit_price <= 0 or stock_quantity < 0:
        flash('Price must be positive and stock quantity cannot be negative.', 'danger')
        return redirect(url_for('products'))

    db=get_db()
    cursor=db.cursor()
    try:
        cursor.execute('''
            INSERT INTO Product (name, sku, stock_quantity, unit_price, supplier_id)
            VALUES (?, ?, ?, ?, ?)
        ''', (name, sku, stock_quantity, unit_price, supplier_id))
        db.commit()
        flash('Product added successfully!', 'success')
    except sqlite3.IntegrityError:
        flash(f'Error: Product with SKU "{sku}" already exists or supplier does not exist.', 'danger')
    except Exception as e:
        flash(f'An error occurred: {e}', 'danger')
    return redirect(url_for('products'))

@app.route('/edit_product/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    """loads the edit product page and handles product updates."""
    db= get_db()
    product=get_product_by_id(product_id)
    suppliers_list= get_all_suppliers()

    if not product:
        flash('Product not found.', 'danger')
        return redirect(url_for('products'))

    if request.method=='POST':
        name=request.form['name']
        sku= request.form['sku']
        try:
            unit_price= float(request.form['unit_price'])
            stock_quantity= int(request.form['stock_quantity'])
            supplier_id =int(request.form['supplier_id'])
        except ValueError:
            flash('Invalid input for price, quantity, or supplier. Please ensure they are numbers.', 'danger')
            return redirect(url_for('edit_product',product_id=product_id))

        if unit_price <= 0 or stock_quantity < 0:
            flash('Price must be positive and stock quantity cannot be negative.', 'danger')
            return redirect(url_for('edit_product',product_id=product_id))

        try:
            db.execute('''
                UPDATE Product
                SET name = ?, sku = ?, stock_quantity = ?, unit_price = ?, supplier_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (name, sku, stock_quantity, unit_price, supplier_id, product_id))
            db.commit()
            flash('Product updated successfully!', 'success')
            return redirect(url_for('products'))
        except sqlite3.IntegrityError:
            flash(f'Error: Product with SKU "{sku}" already exists or supplier does not exist.', 'danger')
        except Exception as e:
            flash(f'An error occurred: {e}','danger')

    return render_template('edit_product.html', product=product, suppliers=suppliers_list)


@app.route('/delete_product/<int:product_id>',methods=['POST'])
def delete_product(product_id):
    """handles deleting a product from the db"""
    db = get_db()
    try:
        #check if there are any transactions associated with this product
        transaction_count=db.execute('SELECT COUNT(*) FROM "Transaction" WHERE product_id = ?',(product_id,)).fetchone()[0]
        if transaction_count > 0:
            flash('Cannot delete product. It has associated transactions. Please delete transactions first.','danger')
            return redirect(url_for('products'))

        db.execute('DELETE FROM Product WHERE id = ?',(product_id,))
        db.commit()
        flash('Product deleted successfully!', 'success')
    except Exception as e:
        flash(f'An error occurred while deleting the product: {e}','danger')
    return redirect(url_for('products'))

@app.route('/suppliers')
def suppliers():
    """loads the suppliers page, show all suppliers and add form"""
    suppliers_list=get_all_suppliers()
    return render_template('suppliers.html', suppliers=suppliers_list)

@app.route('/add_supplier', methods=['POST'])
def add_supplier():
    """logic for adding a new supplier to the database."""
    name=request.form['name']
    contact_email=request.form.get('contact_email')

    db=get_db()
    cursor=db.cursor()
    try:
        cursor.execute('''
            INSERT INTO Supplier (name, contact_email)
            VALUES (?, ?)
        ''', (name,contact_email))
        db.commit()
        flash('Supplier added successfully!', 'success')
    except sqlite3.IntegrityError:
        flash(f'Error: Supplier with name "{name}" already exists.', 'danger')
    except Exception as e:
        flash(f'An error occurred: {e}', 'danger')
    return redirect(url_for('suppliers'))


@app.route('/delete_supplier/<int:supplier_id>', methods=['POST'])
def delete_supplier(supplier_id):
    """logic for deleting a supplier from the db only if no products are associated."""
    db=get_db()
    try:
        product_count=db.execute('SELECT COUNT(*) FROM Product WHERE supplier_id = ?',(supplier_id,)).fetchone()[0]
        if product_count > 0:
            flash('Cannot delete supplier. Products are associated with this supplier.','danger')
        else:
            db.execute('DELETE FROM Supplier WHERE id = ?', (supplier_id,))
            db.commit()
            flash('Supplier deleted successfully!', 'success')
    except Exception as e:
        flash(f'An error occurred while deleting the supplier: {e}', 'danger')
    return redirect(url_for('suppliers'))

@app.route('/transactions')
def transactions():
    """loads the transactions page... showing transaction history and a form to add new transaction"""
    transactions_list =get_all_transactions()
    products_list=get_all_products()
    current_date=datetime.now().strftime('%Y-%m-%d')
    return render_template('transactions.html',
                           transactions=transactions_list,
                           products=products_list,
                           current_date=current_date)

@app.route('/add_transaction',methods=['POST'])
def add_transaction():
    """logic for adding a new transaction and updating product stock"""
    product_id=request.form['product_id']
    transaction_type = request.form['type']
    date =request.form['date']
    try:
        quantity=int(request.form['quantity'])
        unit_price=float(request.form['unit_price'])
    except ValueError:
        flash('Invalid input for quantity or price. Please ensure they are numbers.', 'danger')
        return redirect(url_for('transactions'))

    if quantity <= 0 or unit_price <= 0:
        flash('Quantity and Unit Price must be positive.', 'danger')
        return redirect(url_for('transactions'))

    db=get_db()
    cursor=db.cursor()
    product=get_product_by_id(product_id)

    if not product:
        flash('Selected product not found.', 'danger')
        return redirect(url_for('transactions'))

    new_stock=product['stock_quantity']

    try:
        if transaction_type=='sale':
            if new_stock < quantity:
                flash(f'Not enough stock for sale! Only {new_stock} units available for {product["name"]}.', 'danger')
                return redirect(url_for('transactions'))
            new_stock-=quantity
        elif transaction_type == 'purchase':
            new_stock = quantity+ new_stock
        else:
            flash('Invalid transaction type.', 'danger')
            return redirect(url_for('transactions'))

        cursor.execute('''
            INSERT INTO "Transaction" (product_id, quantity, type, date, unit_price)
            VALUES (?, ?, ?, ?, ?)
        ''', (product_id,quantity,transaction_type,date,unit_price))

        cursor.execute('''
            UPDATE Product
            SET stock_quantity = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (new_stock,product_id))

        db.commit()
        flash('Transaction added and stock updated successfully!', 'success')
    except Exception as e:
        db.rollback()
        flash(f'An error occurred during transaction: {e}', 'danger')
    return redirect(url_for('transactions'))


@app.route('/edit_transaction/<int:transaction_id>', methods=['GET', 'POST'])
def edit_transaction(transaction_id):
    """loads the edit transaction page and handles transaction updates"""
    db=get_db()
    transaction=get_transaction_by_id(transaction_id)
    products_list=get_all_products()

    if not transaction:
        flash('Transaction not found.', 'danger')
        return redirect(url_for('transactions'))

    if request.method=='POST':
        new_product_id= int(request.form['product_id'])
        new_type =request.form['type']
        new_date_str =request.form['date']
        try:
            new_quantity=int(request.form['quantity'])
            new_unit_price=float(request.form['unit_price'])
        except ValueError:
            flash('Invalid input for quantity or price. Please ensure they are numbers.', 'danger')
            return redirect(url_for('edit_transaction',transaction_id=transaction_id))

        if new_quantity <=0 or new_unit_price <= 0:
            flash('Quantity and Unit Price must be positive.', 'danger')
            return redirect(url_for('edit_transaction',transaction_id=transaction_id))

        original_txn = get_transaction_by_id(transaction_id)
        original_product = get_product_by_id(original_txn['product_id'])

        if not original_product:
            flash('Original product for this transaction not found!', 'danger')
            return redirect(url_for('transactions'))

        try:
            db_conn=get_db()
            cursor=db_conn.cursor()

            #revert stock change for the original transaction
            temp_stock = original_product['stock_quantity']
            if original_txn['type']== 'sale':
                temp_stock += original_txn['quantity']
            elif original_txn['type']=='purchase':
                temp_stock -=original_txn['quantity']

            #apply new stock change to the affected product
            target_product=get_product_by_id(new_product_id)
            if not target_product:
                flash('New selected product not found!', 'danger')
                return redirect(url_for('edit_transaction', transaction_id=transaction_id))

            #if product ID changed, adjust stock for original product before applying to new product
            if original_txn['product_id'] != new_product_id:
                cursor.execute('UPDATE Product SET stock_quantity = ? WHERE id = ?',
                               (temp_stock, original_txn['product_id']))
                current_target_stock=target_product['stock_quantity']
            else:
                current_target_stock =temp_stock #  curr product== temp_stock

            if new_type=='sale':
                if current_target_stock< new_quantity:
                    flash(f'Not enough stock for sale! Only {current_target_stock} units available for {target_product["name"]}.', 'danger')
                    db_conn.rollback()
                    return redirect(url_for('edit_transaction', transaction_id=transaction_id))
                current_target_stock -=new_quantity
            elif new_type=='purchase':
                current_target_stock+=new_quantity

            cursor.execute('''
                UPDATE Product
                SET stock_quantity = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (current_target_stock, new_product_id))


            #update the transaction record
            cursor.execute('''
                UPDATE "Transaction"
                SET product_id = ?, quantity = ?, type = ?, date = ?, unit_price = ?
                WHERE id = ?
            ''', (new_product_id, new_quantity,new_type,new_date_str,new_unit_price,transaction_id))
            db_conn.commit()
            flash('Transaction updated successfully!','success')
            return redirect(url_for('transactions'))
        except Exception as e:
            db_conn.rollback()
            flash(f'An error occurred during transaction update: {e}', 'danger')

    return render_template('edit_transaction.html',
                           transaction=transaction,
                           products=products_list,
                           current_date=transaction['date'].strftime('%Y-%m-%d'))


@app.route('/delete_transaction/<int:transaction_id>', methods=['POST'])
def delete_transaction(transaction_id):
    """loads deleting a transaction and reverting product stoc"""
    db=get_db()
    cursor=db.cursor()
    transaction =get_transaction_by_id(transaction_id)

    if not transaction:
        flash('Transaction not found.', 'danger')
        return redirect(url_for('transactions'))

    product_id= transaction['product_id']
    quantity=transaction['quantity']
    transaction_type=transaction['type']

    try:
        # get current product stock
        product=get_product_by_id(product_id)
        if not product:
            flash('Associated product not found for this transaction.', 'danger')
            return redirect(url_for('transactions'))

        new_stock=product['stock_quantity']

        #revert stock change
        if transaction_type == 'sale':
            new_stock += quantity
        elif transaction_type == 'purchase':
            # ensure stock doesnt go negative if a purchase that made it positive is deleted
            if new_stock-quantity< 0:
                 flash(f'Cannot delete purchase transaction. Stock for {product["name"]} would become negative.', 'danger')
                 return redirect(url_for('transactions'))
            new_stock-=quantity

        #update product stock
        cursor.execute('''
            UPDATE Product
            SET stock_quantity = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (new_stock,product_id))

        #delete the transaction
        cursor.execute('DELETE FROM "Transaction" WHERE id = ?', (transaction_id,))
        db.commit()
        flash('Transaction deleted and stock reverted successfully!', 'success')
    except Exception as e:
        db.rollback()
        flash(f'An error occurred while deleting transaction: {e}', 'danger')
    return redirect(url_for('transactions'))


@app.route('/reports')
def reports():
    """loads the reports page with inventory summaries and charts"""
    db=get_db()

    total_value_row=db.execute('SELECT SUM(stock_quantity * unit_price) FROM Product').fetchone()
    total_value=round(total_value_row[0] if total_value_row[0] is not None else 0, 2)

    low_stock_products_raw=db.execute('''
        SELECT p.id, p.name, p.stock_quantity, s.name AS supplier_name
        FROM Product p
        LEFT JOIN Supplier s ON p.supplier_id = s.id
        WHERE p.stock_quantity < 10
        ORDER BY p.stock_quantity ASC
    ''').fetchall()
    low_stock_count =len(low_stock_products_raw)

    supplier_count= db.execute('SELECT COUNT(*) FROM Supplier').fetchone()[0]



    # sales over time (Units Sold)
    sales_data_raw=db.execute('''
        SELECT
            strftime('%Y-%m', date) as month,
            SUM(quantity) as total_sold
        FROM "Transaction"
        WHERE type = 'sale'
        GROUP BY month
        ORDER BY month DESC
        LIMIT 6
    ''').fetchall()
    sales_months= [row['month'] for row in reversed(sales_data_raw)]
    sales_values=[row['total_sold'] for row in reversed(sales_data_raw)]

    # net sales value over time
    net_sales_value_raw = db.execute('''
        SELECT
            strftime('%Y-%m', date) as month,
            SUM(quantity * unit_price) as total_sales_value
        FROM "Transaction"
        WHERE type = 'sale'
        GROUP BY month
        ORDER BY month DESC
        LIMIT 6
    ''').fetchall()
    net_sales_months = [row['month'] for row in reversed(net_sales_value_raw)]
    net_sales_values = [round(row['total_sales_value'], 2) for row in reversed(net_sales_value_raw)]


    # net profit over time
    net_profit_raw= db.execute('''
        SELECT
            strftime('%Y-%m', date) as month,
            SUM(CASE WHEN type = 'sale' THEN quantity * unit_price ELSE 0 END) -
            SUM(CASE WHEN type = 'purchase' THEN quantity * unit_price ELSE 0 END) AS net_profit
        FROM "Transaction"
        GROUP BY month
        ORDER BY month DESC
        LIMIT 6
    ''').fetchall()
    net_profit_months=[row['month'] for row in reversed(net_profit_raw)]
    net_profit_values= [round(row['net_profit'], 2) for row in reversed(net_profit_raw)]


    top_products_raw=db.execute('''
        SELECT
            p.name,
            SUM(t.quantity) AS total_sold_quantity
        FROM "Transaction" t
        JOIN Product p ON t.product_id = p.id
        WHERE t.type = 'sale'
        GROUP BY p.name
        ORDER BY total_sold_quantity DESC
        LIMIT 5
    ''').fetchall()

    top_products_names=[row['name'] for row in top_products_raw]
    top_products_counts=[row['total_sold_quantity'] for row in top_products_raw]


    purchase_count=db.execute("SELECT COUNT(*) FROM \"Transaction\" WHERE type = 'purchase'").fetchone()[0]
    sale_count=db.execute("SELECT COUNT(*) FROM \"Transaction\" WHERE type = 'sale'").fetchone()[0]
    type_counts= [purchase_count, sale_count]


    return render_template('reports.html',
                           total_value=total_value,
                           low_stock_count=low_stock_count,
                           supplier_count=supplier_count,
                           low_stock_products=low_stock_products_raw,
                           sales_months=sales_months,
                           sales_values=sales_values,
                           net_sales_months=net_sales_months, # New data
                           net_sales_values=net_sales_values, # New data
                           net_profit_months=net_profit_months, # New data
                           net_profit_values=net_profit_values, # New data
                           top_products_names=top_products_names,
                           top_products_counts=top_products_counts,
                           type_counts=type_counts)

@app.route('/api/suggest_reorder/<int:product_id>', methods=['GET'])
def api_suggest_reorder(product_id):
    response_data,status_code=suggest_reorder_quantity_from_ai(product_id)
    return jsonify(response_data),status_code

if __name__=='__main__':
    with app.app_context():
        init_db()
    app.run(debug=True)

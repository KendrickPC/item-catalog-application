
from flask import Flask, render_template, url_for, request, redirect, flash, jsonify, make_response
from flask import session as login_session
from sqlalchemy import create_engine, asc, desc
from sqlalchemy.orm import sessionmaker
from database_setup import *
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import os, random, string, datetime, json, httplib2, requests
# Import login_required from login_decorator.py
from login_decorator import login_required

app = Flask(__name__)


CLIENT_ID = json.loads(
    open('client_secrets.json', 'r').read())['web']['client_id']
APPLICATION_NAME = "Item-Catalog"

# Connect to database
engine = create_engine('sqlite:///catalog.db')
Base.metadata.bind = engine
# Create session
DBSession = sessionmaker(bind=engine)
session = DBSession()

# Create a state token to prevent request forgery.
# Store it in the session for later validation.
@app.route('/login')
def showLogin(methods=['GET','POST']):
    if request.method == 'GET':
        state = ''.join(random.choice(string.ascii_uppercase + string.digits)
            for x in xrange(32))
        login_session['state'] = state
        return render_template('login.html', STATE=state)
    else:
        return 'The current session state is %s'%login_session['state']


@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Fail
    if request.args.get('state') != login_session['state']:
        return my_response(json.dumps('Invalid state parameter.'), 401)

    # Success
    code = request.data
    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)

    except FlowExchangeError:
        return my_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)

    access_token = credentials.access_token
    gplus_id = credentials.id_token['sub']
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'%
        access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])

    # Check that the access token is valid.
    if result.get('error') is not None:
        return my_response(json.dumps(result.get('error')), 500)

    elif result['user_id'] != gplus_id:
        return my_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)

    elif result['issued_to'] != CLIENT_ID:
        print "Token's client ID does not match app's."
        return my_response(
            json.dumps("Token's client ID does not match app's."), 401)

    # See if the user is already logged in
    stored_credentials = login_session.get('credentials')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_credentials is not None and gplus_id == stored_gplus_id:
        return my_response(
            json.dumps('Current user is already connected.'), 200)

    # Store the access token in the session for later use.
    login_session['provider'] = 'google'
    login_session['access_token'] = access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)
    data = answer.json()

    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']

    # See if the user exists. If not, make a new user.
    # Store the user id in the login session
    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    # Closing
    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: 150px;'
    output += '-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '
    flash("you are now logged in as %s" % login_session['username'])
    print "done!"
    return output

# End GConnect

# User Helper Functions
def createUser(login_session):
    newUser = User(name=login_session['username'], email=login_session[
                   'email'], picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    return user.id


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except:
        return None

@app.route('/gdisconnect')
def gdisconnect():
    # Only disconnect a connected user.
    access_token = login_session.get('access_token')
    if access_token is None:
        return my_response(json.dumps('Current user not connected.'), 401)

    # Execute HTTP GET request to revoke current token.
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % access_token
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]

    # For whatever reason, the given token was invalid.
    if result['status'] != '200':
        return my_response(
            json.dumps('Failed to revoke token for given user.'), 400)
# End gdisconnect

# Begin fbconnect
# https://developers.facebook.com/docs/facebook-login/web
@app.route('/fbconnect', methods=['POST'])
def fbconnect():
    if request.args.get('state') != login_session['state']:
        return resPaj('Invalid state parameter.', 401)
    access_token = request.data

    #Exchange client token for long-lived server-side token with GET
    #/oauth/access_token?grant_type=fb_exchange_token&client_id={app-
    #id}&client_secret={app-secret}&fb_exchange_token={short-lived-token}
    app_id = json.loads(open('fb_client_secrets.json', 'r').read())['web']['app_id']
    app_secret = json.loads(open('fb_client_secrets.json', 'r').read())['web']['app_secret']
    url = 'https://graph.facebook.com/v2.9/oauth/access_token?grant_type=fb_exchange_token&client_id=%s&client_secret=%s&fb_exchange_token=%s' % (app_id, app_secret, access_token)
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    print result

    #Use token to get user info from API
    userinfo_url = "https://graph.facebook.com/v2.2/me"
    #strip expire tag from access token
    data = json.loads(result)
    token = 'access_token=' + data['access_token']

    url = 'https://graph.facebook.com/v2.8/me?%s&fields=name,id,email' % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    print 'new result:'
    print result

    data = json.loads(result)
    print data
    login_session['provider'] = 'facebook'
    login_session['username'] = data['name']
    login_session['email'] = data.get('email')
    if login_session['email'] is None:
        login_session['email'] = 'facebook@facebook.com'
    login_session['facebook_id'] = data['id']

    #Get user picture
    url = 'https://graph.facebook.com/v2.2/me/picture?%s&redirect=0&height=200&width=200' % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    print 'result with pic:'
    print result
    data = json.loads(result)
    print data

    login_session['picture'] = data['data']['url']

    #check if user exists
    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 160px; height: 160px;'
    output += 'border-radius: 80px; -webkit-border-radius: 80px;'
    output += '-moz-border-radius: 80px;"> '
    flash("you are now logged in as %s" % login_session['username'])
    print "done!"
    return output
# End fbconnect

# Begin fbdisconnect

@app.route('/fbdisconnect')
def fbdisconnect():
    facebook_id = login_session['facebook_id']
    url = 'https://graph.facebook.com/%s/permissions'%facebook_id
    h = httplib2.Http()
    result = h.request(url, 'DELETE')[1]

# End fbdisconnect

# Begin general disconnect merge of Google and Facebook
@app.route('/disconnect')
def disconnect():
    if 'provider' in login_session:
        # Logging Out
        if login_session['provider'] == 'google':
            gdisconnect()
            del login_session['gplus_id']
            del login_session['access_token'] 

        elif login_session['provider'] == 'facebook':
            fbdisconnect()
            del login_session['facebook_id']

        # Delete
        del login_session['username']
        del login_session['email']
        del login_session['picture']
        del login_session['user_id']
        del login_session['provider']
        # Closing
        flash('You have successfully logged out.')
        return redirect(url_for('showCatalog'))
    else:
        flash('You are not logged in.')
        return redirect(url_for('showCatalog'))
# End general disconnect merge of Google and Facebook

# Begin Flask Routing
# Homepage
@app.route('/')
@app.route('/catalog/')
def showCatalog():
    categories = session.query(Category).order_by(asc(Category.name))
    items = session.query(Items).order_by(desc(Items.date)).limit(5)
    return render_template('catalog.html',
                            categories = categories,
                            items = items)

# Category Items
@app.route('/catalog/<path:category_name>/items/')
def showCategory(category_name):
    categories = session.query(Category).order_by(asc(Category.name))
    category = session.query(Category).filter_by(name=category_name).one()
    items = session.query(Items).filter_by(category=category).order_by(asc(Items.name)).all()
    print items
    count = session.query(Items).filter_by(category=category).count()
    creator = getUserInfo(category.user_id)
    if 'username' not in login_session or creator.id != login_session['user_id']:
        return render_template('public_items.html',
                                category = category.name,
                                categories = categories,
                                items = items,
                                count = count)
    else:
        user = getUserInfo(login_session['user_id'])
        return render_template('items.html',
                                category = category.name,
                                categories = categories,
                                items = items,
                                count = count,
                                user=user)

# Display a Specific Item
@app.route('/catalog/<path:category_name>/<path:item_name>/')
def showItem(category_name, item_name):
    item = session.query(Items).filter_by(name=item_name).one()
    creator = getUserInfo(item.user_id)
    categories = session.query(Category).order_by(asc(Category.name))
    if 'username' not in login_session or creator.id != login_session['user_id']:
        return render_template('public_itemdetail.html',
                                item = item,
                                category = category_name,
                                categories = categories,
                                creator = creator)
    else:
        return render_template('itemdetail.html',
                                item = item,
                                category = category_name,
                                categories = categories,
                                creator = creator)

# Add a category
@app.route('/catalog/addcategory', methods=['GET', 'POST'])
@login_required
def addCategory():
    if request.method == 'POST':
        newCategory = Category(
            name=request.form['name'],
            user_id=login_session['user_id'])
        print newCategory
        session.add(newCategory)
        session.commit()
        flash('Category Successfully Added!')
        return redirect(url_for('showCatalog'))
    else:
        return render_template('addcategory.html')

# Edit a category
@app.route('/catalog/<path:category_name>/edit', methods=['GET', 'POST'])
@login_required
def editCategory(category_name):
    editedCategory = session.query(Category).filter_by(name=category_name).one()
    category = session.query(Category).filter_by(name=category_name).one()
    # See if the logged in user is the owner of item
    creator = getUserInfo(editedCategory.user_id)
    user = getUserInfo(login_session['user_id'])
    # If logged in user != item owner redirect them
    if creator.id != login_session['user_id']:
        flash ("You cannot edit this Category. This Category belongs to %s" % creator.name)
        return redirect(url_for('showCatalog'))
    # POST methods
    if request.method == 'POST':
        if request.form['name']:
            editedCategory.name = request.form['name']
        session.add(editedCategory)
        session.commit()
        flash('Category Item Successfully Edited!')
        return  redirect(url_for('showCatalog'))
    else:
        return render_template('editcategory.html',
                                categories=editedCategory,
                                category = category)

# Delete a category
@app.route('/catalog/<path:category_name>/delete', methods=['GET', 'POST'])
@login_required
def deleteCategory(category_name):
    categoryToDelete = session.query(Category).filter_by(name=category_name).one()
    # See if the logged in user is the owner of item
    creator = getUserInfo(categoryToDelete.user_id)
    user = getUserInfo(login_session['user_id'])
    # If logged in user != item owner redirect them
    if creator.id != login_session['user_id']:
        flash ("You cannot delete this Category. This Category belongs to %s" % creator.name)
        return redirect(url_for('showCatalog'))
    if request.method =='POST':
        session.delete(categoryToDelete)
        session.commit()
        flash('Category Successfully Deleted! '+categoryToDelete.name)
        return redirect(url_for('showCatalog'))
    else:
        return render_template('deletecategory.html',
                                category=categoryToDelete)

# Add an item
@app.route('/catalog/add', methods=['GET', 'POST'])
@login_required
def addItem():
    categories = session.query(Category).all()
    if request.method == 'POST':
        newItem = Items(
            name=request.form['name'],
            description=request.form['description'],
            picture=request.form['picture'],
            category=session.query(Category).filter_by(name=request.form['category']).one(),
            date=datetime.datetime.now(),
            user_id=login_session['user_id'])
        session.add(newItem)
        session.commit()
        flash('Item Successfully Added!')
        return redirect(url_for('showCatalog'))
    else:
        return render_template('additem.html',
                                categories=categories)

# Edit an item
@app.route('/catalog/<path:category_name>/<path:item_name>/edit', methods=['GET', 'POST'])
@login_required
def editItem(category_name, item_name):
    editedItem = session.query(Items).filter_by(name=item_name).one()
    categories = session.query(Category).all()
    # See if the logged in user is the owner of item
    creator = getUserInfo(editedItem.user_id)
    user = getUserInfo(login_session['user_id'])
    # If logged in user != item owner redirect them
    if creator.id != login_session['user_id']:
        flash ("You cannot edit this item. This item belongs to %s" % creator.name)
        return redirect(url_for('showCatalog'))
    # POST methods
    if request.method == 'POST':
        if request.form['name']:
            editedItem.name = request.form['name']
        if request.form['description']:
            editedItem.description = request.form['description']
        if request.form['picture']:
            editedItem.picture = request.form['picture']
        if request.form['category']:
            category = session.query(Category).filter_by(name=request.form['category']).one()
            editedItem.category = category
        time = datetime.datetime.now()
        editedItem.date = time
        session.add(editedItem)
        session.commit()
        flash('Category Item Successfully Edited!')
        return  redirect(url_for('showCategory',
                                category_name=editedItem.category.name))
    else:
        return render_template('edititem.html',
                                item=editedItem,
                                categories=categories)

# Delete an item
@app.route('/catalog/<path:category_name>/<path:item_name>/delete', methods=['GET', 'POST'])
@login_required
def deleteItem(category_name, item_name):
    itemToDelete = session.query(Items).filter_by(name=item_name).one()
    category = session.query(Category).filter_by(name=category_name).one()
    categories = session.query(Category).all()
    # See if the logged in user is the owner of item
    creator = getUserInfo(itemToDelete.user_id)
    user = getUserInfo(login_session['user_id'])
    # If logged in user != item owner redirect them
    if creator.id != login_session['user_id']:
        flash ("You cannot delete this item. This item belongs to %s" % creator.name)
        return redirect(url_for('showCatalog'))
    if request.method =='POST':
        session.delete(itemToDelete)
        session.commit()
        flash('Item Successfully Deleted! '+itemToDelete.name)
        return redirect(url_for('showCategory',
                                category_name=category.name))
    else:
        return render_template('deleteitem.html',
                                item=itemToDelete)

# Begin JSON routing
@app.route('/catalog/JSON')
def allItemsJSON():
    categories = session.query(Category).all()
    category_dict = [c.serialize for c in categories]
    for c in range(len(category_dict)):
        items = [i.serialize for i in session.query(Items)\
                    .filter_by(category_id=category_dict[c]["id"]).all()]
        if items:
            category_dict[c]["Item"] = items
    return jsonify(Category=category_dict)

@app.route('/catalog/categories/JSON')
def categoriesJSON():
    categories = session.query(Category).all()
    return jsonify(categories=[c.serialize for c in categories])

@app.route('/catalog/items/JSON')
def itemsJSON():
    items = session.query(Items).all()
    return jsonify(items=[i.serialize for i in items])

@app.route('/catalog/<path:category_name>/items/JSON')
def categoryItemsJSON(category_name):
    category = session.query(Category).filter_by(name=category_name).one()
    items = session.query(Items).filter_by(category=category).all()
    return jsonify(items=[i.serialize for i in items])

@app.route('/catalog/<path:category_name>/<path:item_name>/JSON')
def ItemJSON(category_name, item_name):
    category = session.query(Category).filter_by(name=category_name).one()
    item = session.query(Items).filter_by(name=item_name,\
                                        category=category).one()
    return jsonify(item=[item.serialize])


# url_for static path processor
# remove when deployed
@app.context_processor
def override_url_for():
    return dict(url_for=dated_url_for)

def dated_url_for(endpoint, **values):
    if endpoint == 'static':
        filename = values.get('filename', None)
        if filename:
            file_path = os.path.join(app.root_path,
                                     endpoint, filename)
            values['q'] = int(os.stat(file_path).st_mtime)
    return url_for(endpoint, **values)

# Always at end of file !Important!
if __name__ == '__main__':
    app.secret_key = 'DEV_SECRET_KEY'
    app.debug = True
    app.run(host = '0.0.0.0', port = 5000)
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from huggingface_hub import User
import pandas as pd
import os
from cryptography.fernet import Fernet, InvalidToken
from flask_dance.contrib.google import make_google_blueprint, google
from datetime import datetime, timedelta
import secrets
from flask import send_file, abort


video_tokens = {}   # token : {email, video, expiry}


app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# Google OAuth
app.config["GOOGLE_OAUTH_CLIENT_ID"] = "your_google_client_id"
app.config["GOOGLE_OAUTH_CLIENT_SECRET"] = "your_google_client_secret"
blueprint = make_google_blueprint(scope=["profile", "email"])
app.register_blueprint(blueprint, url_prefix="/login")

# Excel files
USER_FILE = 'user_data.xlsx'
VIDEO_FILE = 'videos.xlsx'
ACCESS_FILE = 'user_video_access.xlsx'

# Create files if not exist
if not os.path.exists(USER_FILE):
    pd.DataFrame(columns=['name','email','password','subscribed','subscription_start']).to_excel(USER_FILE,index=False)

if not os.path.exists(VIDEO_FILE):
    videos = pd.DataFrame([
        ['Chocolate Cake','/static/videos/video1.mp4',199],
        ['Vanilla Cake','/static/videos/video2.mp4',149],
        ['Bread Making','/static/videos/video3.mp4',249],
        ['Pastry Art','/static/videos/video4.mp4',199],
        ['Cookies','/static/videos/video1.mp5',199],
        ['Pancakes','/static/videos/video2.mp6',149],
        ['Puddings','/static/videos/video3.mp7',249],
        ['Waffles','/static/videos/video4.mp8',199],
        ['Red Velvet Cake','/static/videos/video1.mp9',199],
        ['Pizza','/static/videos/video2.mp10',149],
        ['Burger','/static/videos/video3.mp11',249],
        ['Sandwich','/static/videos/video4.mp12',199]
    ], columns=['video_name','file_path','price'])
    videos.to_excel(VIDEO_FILE,index=False)

if not os.path.exists(ACCESS_FILE):
    pd.DataFrame(columns=['email','video_name','unlock_date']).to_excel(ACCESS_FILE,index=False)


# Encryption key
KEY_FILE = 'secret.key'
if not os.path.exists(KEY_FILE):
    with open(KEY_FILE,'wb') as f:
        f.write(Fernet.generate_key())
with open(KEY_FILE,'rb') as f:
    key = f.read()
cipher = Fernet(key)

# ---------------- ROUTES ----------------
@app.route('/')
def home():
    if 'email' in session:
        return render_template('dashboard.html', logged_in=True, name=session.get('name'))
    return render_template('dashboard.html', logged_in=False, name=None)


@app.route('/register', methods=['GET','POST'])
def register():
    # your register logic

    if request.method=='POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        df = pd.read_excel(USER_FILE)
        if email in df['email'].values:
            flash("Email already registered!","error")
            return redirect(url_for('register'))
        encrypted = cipher.encrypt(password.encode()).decode()
        df.loc[len(df.index)] = [
            name,
            email,
            encrypted,
            False,
            ""
        ]

        df.to_excel(USER_FILE,index=False)
        flash("Registration Successful! Login now.","success")
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        email = request.form['email']
        password = request.form['password']
        df = pd.read_excel(USER_FILE)
        if email in df['email'].values:
            user = df[df['email']==email].iloc[0]
            try:
                decrypted = cipher.decrypt(user['password'].encode()).decode()
                if password==decrypted:
                    session['email']=email
                    session['name']=user['name']
                    session['subscribed']=bool(user['subscribed'])
                    session['subscription_start']=str(user['subscription_start'])
                    return redirect(url_for('videos'))
                else:
                    flash("Invalid password","error")
            except InvalidToken:
                flash("Password corrupted, reset required","error")
        else:
            flash("Invalid credentials","error")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# ---------------- GOOGLE LOGIN ----------------
@app.route('/google-login')
def google_login():
    if not google.authorized:
        return redirect(url_for("google.login"))
    resp = google.get("/oauth2/v2/userinfo")
    email = resp.json()["email"]
    df = pd.read_excel(USER_FILE)
    if email not in df['email'].values:
        df.loc[len(df.index)] = [resp.json()['name'], email, '', False,'']
        df.to_excel(USER_FILE,index=False)
    session['email']=email
    session['name']=resp.json()['name']
    user = df[df['email']==email].iloc[0]
    session['subscription_start'] = str(user.get('subscription_start', ''))

   # If the column exists, use it; otherwise, set empty
df = pd.read_excel(USER_FILE)

if 'subscription_start' not in df.columns:
    df['subscription_start'] = ''
    df.to_excel(USER_FILE, index=False)



# ---------------- VIDEOS ----------------
@app.route("/videos")
def videos():
    if "email" not in session:
        return redirect(url_for("login"))

    video_df = pd.read_excel(VIDEO_FILE)
    from datetime import datetime, timedelta

    access_df = pd.read_excel(ACCESS_FILE)

    user_access = access_df[access_df["email"] == session["email"]]

    unlocked_videos = {}

    for _, row in user_access.iterrows():
        if pd.isna(row["unlock_date"]):
            continue   # skip broken rows

        unlock_date = datetime.strptime(str(row["unlock_date"]), "%Y-%m-%d")
        expiry = unlock_date + timedelta(days=15)
        days_left = (expiry - datetime.now()).days

        if days_left >= 0:
            unlocked_videos[row["video_name"]] = days_left

            

    videos = []
    for i, row in video_df.iterrows():
       videos.append({
    "name": row["video_name"],
    "price": row["price"],
    "thumbnail": f"/static/images/{row['video_name'].replace(' ','').lower()}.jpg",
    "stream_url": f"/static/videos/{row['video_name'].replace(' ','').lower()}.mp4",
    "unlocked": row["video_name"] in unlocked_videos,
    "days_left": unlocked_videos.get(row["video_name"], None)
})



    return render_template("videos.html", videos=videos)




# ---------------- PURCHASE / SUBSCRIBE ----------------
@app.route('/purchase/<video_name>',methods=['GET','POST'])
def purchase(video_name):
    if 'email' not in session:
        flash("Login required","error")
        return redirect(url_for('login'))

    video_df = pd.read_excel(VIDEO_FILE)
    video = video_df[video_df['video_name']==video_name].iloc[0]

    # Simulate payment
    if request.method=='POST':
        access_df = pd.read_excel(ACCESS_FILE)
        if not ((access_df['email']==session['email']) & (access_df['video_name']==video_name)).any():
            access_df.loc[len(access_df.index)] = [session['email'],video_name]
            access_df.to_excel(ACCESS_FILE,index=False)
        flash(f"Purchased {video_name} successfully!","success")
        return redirect(url_for('videos'))

    return render_template('purchase.html',video=video)

# ---------------- WATCH VIDEO ----------------
@app.route('/watch/<video_name>')
def watch(video_name):
    if 'email' not in session:
        return redirect(url_for('login'))

    video_name = video_name.replace("_", " ")

    access_df = pd.read_excel(ACCESS_FILE)
    user_access = access_df[
        (access_df["email"] == session["email"]) &
        (access_df["video_name"] == video_name)
    ]

    # ❌ User never purchased this video
    if user_access.empty:
        flash("Please purchase this video first", "error")
        return redirect(url_for("subscribe", video_name=video_name.replace(" ", "_")))

    # ⏳ 15-day expiry check
    unlock_date = datetime.strptime(user_access.iloc[0]["unlock_date"], "%Y-%m-%d")

    if datetime.now() > unlock_date + timedelta(days=15):
        flash("Your 15-day access expired. Please re-subscribe.", "error")
        return redirect(url_for("subscribe", video_name=video_name.replace(" ", "_")))

    # ✅ Valid access — create secure token
    token = secrets.token_urlsafe(32)
    expiry = datetime.now() + timedelta(minutes=10)

    video_tokens[token] = {
        "email": session['email'],
        "video": video_name,
        "expiry": expiry
    }

    return render_template("watch.html", video_name=video_name, token=token)


@app.route("/stream/<int:video_id>")
def stream(video_id):
    if video_id not in session.get("unlocked_videos", []):
        return "Unauthorized", 403

    files = {
        1: "videos/video1.mp4",
        2: "videos/video2.mp4",
        3: "videos/video3.mp4",
        4: "videos/video4.mp4",
        5: "videos/video5.mp4",
        6: "videos/video6.mp4",
        7: "videos/video7.mp4",
        8: "videos/video8.mp4"
    }
    return send_file(files[video_id], conditional=True)






# ---------------- SUBSCRIBE FOR ANY VIDEO ----------------
@app.route('/subscribe/<video_name>', methods=['GET','POST'])
def subscribe(video_name):

    # 🔴 LOGIN CHECK (ADDITION)
    if 'email' not in session:
        flash("Login first to unlock videos!", "error")
        return redirect(url_for('login'))

    # Convert underscores to spaces
    video_name_clean = video_name.replace('_', ' ')

    # Load all videos
    video_df = pd.read_excel(VIDEO_FILE)

    # If the video is not found in Excel, select the first video as default
    if video_name_clean not in video_df['video_name'].values:
        video = video_df.iloc[0]
    else:
        video = video_df[video_df['video_name'] == video_name_clean].iloc[0]

    # POST request: process payment
    if request.method == 'POST':
        access_df = pd.read_excel(ACCESS_FILE)
        if not ((access_df['email'] == session['email']) & 
                (access_df['video_name'] == video['video_name'])).any():
            from datetime import datetime

            today = datetime.now().strftime("%Y-%m-%d")

            access_df.loc[len(access_df.index)] = [
                session['email'],
                video['video_name'],
                today
            ]

            access_df.to_excel(ACCESS_FILE, index=False)

        return redirect(url_for('videos', success=video['video_name']))


    return render_template('subscribe.html', video=video)



@app.route("/payment/<video_name>", methods=["GET", "POST"])
def payment(video_name):
    if 'email' not in session:
        return jsonify({"status":"error","message":"Login required"})

    video_name_clean = video_name.replace("_", " ")
    video_df = pd.read_excel(VIDEO_FILE)

    if video_name_clean not in video_df["video_name"].values:
        return jsonify({"status":"error","message":"Video not found"})

    video = video_df[video_df["video_name"] == video_name_clean].iloc[0]

    if request.method == "POST":
        method = request.form.get("method")

        # ---------- UPI PIN CHECK ----------
        if method in ["gpay","phonepe"]:
            pin = request.form.get("upi_pin")
            if pin != "1234":
                return jsonify({"status":"error","message":"❌ Wrong UPI PIN"})

        # ---------- CARD CHECK ----------
        if method == "card":
            card = request.form.get("card_number")
            cvv = request.form.get("cvv")
            exp = request.form.get("expiry")

            if not card or not cvv or not exp:
                return jsonify({"status":"error","message":"❌ Invalid Card Details"})

        # ---------- SAVE ACCESS ----------
        # ---------- SAVE ACCESS ----------
        access_df = pd.read_excel(ACCESS_FILE)

        if not ((access_df["email"] == session["email"]) & 
            (access_df["video_name"] == video_name_clean)).any():

            today = datetime.now().strftime("%Y-%m-%d")

            access_df.loc[len(access_df)] = [
                session["email"],
                video_name_clean,
                today
            ]

            access_df.to_excel(ACCESS_FILE, index=False)


        return jsonify({"status":"success","message":"✅ Payment Successful! Video Unlocked"})

    return render_template("payment.html", video_name=video_name_clean)








@app.route('/subscribe')
def subscribe_redirect():
    return redirect(url_for('videos'))





   

@app.route("/subscribe/<int:video_id>")
def subscribe_video(video_id):
    # Simulated payment success
    session["subscribed"] = True
    session["subscription_start"] = datetime.now().strftime("%Y-%m-%d")

    # OPTIONAL: store unlocked video ids
    unlocked = session.get("unlocked_videos", [])
    if video_id not in unlocked:
        unlocked.append(video_id)
    session["unlocked_videos"] = unlocked

    return redirect(url_for("videos"))


@app.route("/subscribe/<int:video_id>")
def subscribe_page(video_id):
    return render_template("subscribe.html", video_id=video_id)


@app.route('/payment/<video_name>', methods=['GET', 'POST'])
def payment_page(video_name):
    video_name = video_name.replace('_', ' ')

    if request.method == 'POST':
        payment_method = request.form.get('method')

        # UPI PIN CHECK
        if payment_method in ['gpay', 'phonepe']:
            pin = request.form.get('upi_pin')
            if pin != '1234':   # demo correct pin
                return jsonify({'status': 'error', 'message': '❌ Wrong UPI PIN'})
            else:
                return jsonify({'status': 'success'})

        # DEBIT CARD CHECK
        if payment_method == 'card':
            card = request.form.get('card_number')
            cvv = request.form.get('cvv')
            expiry = request.form.get('expiry')

            if not card or not cvv or not expiry:
                return jsonify({'status': 'error', 'message': '❌ Invalid card details'})
            else:
                return jsonify({'status': 'success'})

    return render_template('payment.html', video_name=video_name)



@app.route('/payment/process/<video_name>', methods=['POST'])
def payment_process(video_name):
    if 'email' not in session:
        flash("Login required", "error")
        return redirect(url_for('login'))

    video_name = video_name.replace('_', ' ')

    access_df = pd.read_excel(ACCESS_FILE)
    if not ((access_df['email'] == session['email']) &
            (access_df['video_name'] == video_name)).any():
        access_df.loc[len(access_df)] = [session['email'], video_name]
        access_df.to_excel(ACCESS_FILE, index=False)

    flash(f"{video_name} unlocked successfully!", "success")
    return redirect(url_for('videos', success=1))









# ---------------- RUN SERVER ----------------
if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=8000)


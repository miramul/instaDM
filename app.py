import os
import time
import random
from flask import Flask, render_template, request, jsonify, session
from instagrapi import Client
import threading
import logging
from io import StringIO

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key')

SENT_USERS_FILE = "sent_users.txt"

# ログキャプチャ用のハンドラーを設定
class LogCapture:
    def __init__(self):
        self.log_stream = StringIO()
        self.handler = logging.StreamHandler(self.log_stream)
        self.handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        
        # ルートロガーにハンドラーを追加
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger().addHandler(self.handler)
        
        # 標準出力も記録
        self.stdout_capture = StringIO()
        self.original_stdout = None
    
    def start_capture(self):
        import sys
        self.original_stdout = sys.stdout
        sys.stdout = self.stdout_capture
    
    def stop_capture(self):
        import sys
        if self.original_stdout:
            sys.stdout = self.original_stdout
    
    def get_logs(self):
        # ログストリームと標準出力の両方を取得
        return self.log_stream.getvalue() + self.stdout_capture.getvalue()

# グローバルにログキャプチャを設定
log_capture = LogCapture()
log_entries = []

def delete_session_file(username):
    session_file = f"session_{username}.json"
    if os.path.exists(session_file):
        os.remove(session_file)
        print(f"セッションファイル {session_file} を削除しました。")

def login_with_cookie(username, password):
    if not username or not password:
        return None

    cl = Client()
    session_file = f"session_{username}.json"
    delete_session_file(username)

    if os.path.exists(session_file):
        try:
            cl.load_settings(session_file)
            cl.login(username, password)
            print(f"✅ {username} クッキーを使ってログイン成功！")
            return cl
        except Exception as e:
            print(f"⚠️ {username} クッキーの読み込みに失敗: {str(e)}。通常のログインを試みます。")

    try:
        cl.login(username, password)
        cl.dump_settings(session_file)
        print(f"✅ {username} 通常のログイン成功！")
        return cl
    except Exception as e:
        print(f"❌ {username} ログイン失敗: {str(e)}")
        return None

def get_top_100_followers(cl, target_account):
    try:
        user_id = cl.user_id_from_username(target_account.strip())
        followers = cl.user_followers(user_id, amount=100)
        return [f.username for f in followers.values()]
    except Exception as e:
        print(f"⚠️ {target_account} のフォロワー取得に失敗しました: {str(e)}")
        return []

def follow_if_not_following(cl, username):
    try:
        user_id = cl.user_id_from_username(username)
        friendship = cl.user_info(user_id).friendship_status
        if not friendship.following:
            cl.user_follow(user_id)
            print(f"✅ {username} をフォローしました！")
            time.sleep(random.randint(600, 1200))  # ウェブで実行する場合は待機時間を短縮
        else:
            print(f"➡️ {username} はすでにフォローしています。")
    except Exception as e:
        print(f"❌ {username} のフォローに失敗: {e}")

def load_sent_users():
    if os.path.exists(SENT_USERS_FILE):
        with open(SENT_USERS_FILE, "r", encoding="utf-8") as file:
            return set(file.read().splitlines())
    return set()

def save_sent_user(username):
    with open(SENT_USERS_FILE, "a", encoding="utf-8") as file:
        file.write(username + "\n")

def send_dm_task(username, password, target_accounts, dm_message, callback=None):
    results = {"status": "processing", "success": 0, "failed": 0, "message": "処理中..."}
    
    try:
        cl = login_with_cookie(username, password)
        
        if not cl:
            results = {"status": "error", "message": "ログインに失敗しました。"}
            if callback:
                callback(results)
            return results

        sent_users = load_sent_users()
        all_target_users = []
        
        for target in target_accounts:
            followers = get_top_100_followers(cl, target)
            new_followers = [f for f in followers if f not in sent_users]
            all_target_users.extend(new_followers)

        if not all_target_users:
            results = {"status": "error", "message": "送信可能な新規フォロワーが見つかりませんでした。"}
            if callback:
                callback(results)
            return results

        success_users, failed_users = [], []
        for user in all_target_users:
            try:
                follow_if_not_following(cl, user)
                user_info = cl.user_info_by_username(user.strip())
                user_id = user_info.pk
                profile_name = user_info.full_name if user_info.full_name else user
                personalized_message = f"{profile_name}様\n\n{dm_message}"
                cl.direct_send(personalized_message, [user_id])
                time.sleep(random.randint(1500, 2100))  # ウェブで実行する場合は待機時間を短縮
                success_users.append(user.strip())
                save_sent_user(user.strip())
                results["success"] += 1
            except Exception as e:
                print(f"DM送信エラー ({user}): {str(e)}")
                failed_users.append(user.strip())
                results["failed"] += 1
                time.sleep(60)  # エラー時は短い待機

        results = {
            "status": "complete", 
            "success": len(success_users), 
            "failed": len(failed_users),
            "message": f"DM送信完了: 成功 {len(success_users)}件、失敗 {len(failed_users)}件"
        }
        
    except Exception as e:
        results = {"status": "error", "message": f"エラーが発生しました: {str(e)}"}
    
    if callback:
        callback(results)
    return results

# 各ユーザーのタスク状態を保存
tasks = {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/send-dm', methods=['POST'])
def send_dm_api():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    target_accounts = [t.strip() for t in data.get('targets', '').split(',') if t.strip()]
    dm_message = data.get('message', '').strip()

    if not all([username, password, target_accounts, dm_message]):
        return jsonify({"status": "error", "message": "すべての情報を入力してください。"})

    # ユーザーごとにユニークなタスクIDを生成
    task_id = f"task_{username}_{int(time.time())}"
    tasks[task_id] = {"status": "starting", "message": "タスクを開始しています..."}
    
    # ログキャプチャを開始
    log_capture.start_capture()
    
    # バックグラウンドでDM送信を実行
    def update_task_status(result):
        tasks[task_id] = result
        # タスク完了時のログを保存
        result["logs"] = log_capture.get_logs()
        log_capture.stop_capture()
        
    thread = threading.Thread(
        target=send_dm_task, 
        args=(username, password, target_accounts, dm_message, update_task_status)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({"status": "started", "task_id": task_id})

@app.route('/api/task-status/<task_id>', methods=['GET'])
def get_task_status(task_id):
    if task_id in tasks:
        return jsonify(tasks[task_id])
    return jsonify({"status": "error", "message": "タスクが見つかりません"})

# 実行ログを表示するためのルート
@app.route('/logs')
def view_logs():
    return render_template('logs.html')

@app.route('/api/logs', methods=['GET'])
def get_logs():
    # 全てのタスクからログを収集
    all_logs = []
    for task_id, task_data in tasks.items():
        if "logs" in task_data:
            all_logs.append({
                "task_id": task_id,
                "timestamp": task_id.split("_")[-1],
                "logs": task_data["logs"]
            })
    
    # 時間順にソート
    all_logs.sort(key=lambda x: x["timestamp"], reverse=True)
    
    return jsonify(all_logs)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

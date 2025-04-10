import os
import time
import random
import json
import logging
import threading
from pathlib import Path
from io import StringIO
from flask import Flask, render_template, request, jsonify, session
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ChallengeRequired, TwoFactorRequired

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key')

SENT_USERS_FILE = "sent_users.txt"

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("instagram_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("instagram_bot")

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

class InstagramBot:
    def __init__(self, username, password, session_file=None, proxy=None):
        """
        Instagram Bot の初期化
        
        Args:
            username (str): Instagram ユーザー名
            password (str): Instagram パスワード
            session_file (str, optional): セッションファイルのパス
            proxy (str, optional): プロキシ URL (例: "http://user:pass@ip:port")
        """
        self.username = username
        self.password = password
        self.session_file = session_file or f"session_{username}.json"
        self.client = Client()
        
        # プロキシが提供されている場合は設定
        if proxy:
            self.client.set_proxy(proxy)
            logger.info(f"プロキシを設定しました: {proxy}")
        
        # ユーザーエージェントの設定
        self.client.user_agent = "Instagram 269.0.0.18.75 Android (30/11; 480dpi; 1080x2400; samsung; SM-A505F; a50; exynos9610; en_US; 418154036)"
        logger.info(f"ユーザーエージェントを設定しました: {self.client.user_agent}")

    def _save_session(self):
        """セッション情報を保存"""
        session_data = {
            "cookies": self.client.get_settings()["cookies"],
            "uuid": self.client.uuid,
            "device_id": self.client.device_id,
            "user_id": self.client.user_id,
            "authorization_data": self.client.authorization_data,
        }
        
        with open(self.session_file, "w") as f:
            json.dump(session_data, f)
        
        logger.info(f"セッションを保存しました: {self.session_file}")

    def _load_session(self):
        """保存されたセッション情報を読み込み"""
        if not os.path.exists(self.session_file):
            logger.warning(f"セッションファイルが見つかりません: {self.session_file}")
            return False
        
        try:
            session = self.client.load_settings(self.session_file)
            logger.info(f"セッションを読み込みました: {self.session_file}")
            return True
        except Exception as e:
            logger.error(f"セッションの読み込みに失敗しました: {e}")
            return False

    def _handle_challenge(self, challenge_type):
        """
        認証チャレンジの処理
        
        Args:
            challenge_type: チャレンジのタイプ
        """
        if challenge_type == "phone":
            logger.info("電話番号による認証が要求されました")
            # SMS 要求を送信
            self.client.challenge_send_code("1")  # 1 = SMS, 0 = Email
            
            # SMSコードを外部ファイルから読み込む仕組み
            # ここでは、外部スクリプトかWebhookがファイルにコードを書き込むことを想定
            code_file = f"auth_code_{self.username}.txt"
            
            # コードファイルが生成されるのを待つ（最大10分）
            wait_time = 0
            while not os.path.exists(code_file) and wait_time < 600:
                time.sleep(5)
                wait_time += 5
                logger.info(f"認証コードを待っています... {wait_time}秒経過")
            
            if os.path.exists(code_file):
                with open(code_file, "r") as f:
                    code = f.read().strip()
                # コードファイルを削除
                os.remove(code_file)
                
                # コードを送信
                self.client.challenge_send_security_code(code)
                logger.info("認証コードを送信しました")
                return True
            else:
                logger.error("認証コードの取得に失敗しました")
                return False
        else:
            logger.error(f"未対応の認証タイプ: {challenge_type}")
            return False

    def _handle_two_factor(self):
        """二要素認証の処理"""
        logger.info("二要素認証が要求されました")
        
        # 二要素認証コードを外部ファイルから読み込む
        code_file = f"2fa_code_{self.username}.txt"
        
        # コードファイルが生成されるのを待つ（最大10分）
        wait_time = 0
        while not os.path.exists(code_file) and wait_time < 600:
            time.sleep(5)
            wait_time += 5
            logger.info(f"二要素認証コードを待っています... {wait_time}秒経過")
        
        if os.path.exists(code_file):
            with open(code_file, "r") as f:
                code = f.read().strip()
            # コードファイルを削除
            os.remove(code_file)
            
            # 二要素認証コードを送信
            self.client.login_2fa(code)
            logger.info("二要素認証コードを送信しました")
            return True
        else:
            logger.error("二要素認証コードの取得に失敗しました")
            return False

    def login(self, max_retries=3):
        """
        Instagram にログイン
        
        Args:
            max_retries (int): 最大再試行回数
        
        Returns:
            bool: ログイン成功時に True、失敗時に False
        """
        # 既存のセッションがあれば読み込む
        if self._load_session():
            try:
                # セッションのテスト
                self.client.get_timeline_feed()
                logger.info("既存のセッションでログインに成功しました")
                return True
            except LoginRequired:
                logger.warning("セッションが期限切れ。再ログインします...")
        
        # リトライカウンター
        retries = 0
        
        while retries < max_retries:
            try:
                # ランダムな待機時間（10〜30秒）
                sleep_time = random.randint(10, 30)
                logger.info(f"ログイン試行前に {sleep_time} 秒待機します")
                time.sleep(sleep_time)
                
                # ログイン試行
                logged_in = self.client.login(self.username, self.password)
                
                if logged_in:
                    logger.info("ログインに成功しました")
                    self._save_session()
                    return True
            
            except ChallengeRequired as e:
                logger.warning(f"チャレンジが要求されました: {e}")
                
                if self._handle_challenge(e.challenge_type):
                    # チャレンジ成功後にセッションを保存
                    self._save_session()
                    return True
                else:
                    logger.error("チャレンジの解決に失敗しました")
            
            except TwoFactorRequired:
                logger.warning("二要素認証が要求されました")
                
                if self._handle_two_factor():
                    # 二要素認証成功後にセッションを保存
                    self._save_session()
                    return True
                else:
                    logger.error("二要素認証の解決に失敗しました")
            
            except Exception as e:
                logger.error(f"ログイン中にエラーが発生しました: {e}")
            
            # リトライの前に待機（指数バックオフ）
            wait_time = random.randint(60, 180) * (2 ** retries)
            logger.info(f"再試行前に {wait_time} 秒待機します")
            time.sleep(wait_time)
            
            retries += 1
        
        logger.error(f"最大試行回数 ({max_retries}) に達しました。ログインに失敗しました。")
        return False

# セッションファイルを削除する関数
def delete_session_file(username):
    session_file = f"session_{username}.json"
    if os.path.exists(session_file):
        os.remove(session_file)
        print(f"セッションファイル {session_file} を削除しました。")

# 改良されたログイン関数
def login_with_cookie(username, password):
    if not username or not password:
        return None

    # InstagramBotを使用してログイン処理を行う
    bot = InstagramBot(username, password)
    if bot.login():
        print(f"✅ {username} ログイン成功！")
        return bot.client
    else:
        print(f"❌ {username} ログイン失敗")
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

# Instagram DM 自動送信アプリ

このアプリケーションは、Instagramのフォロワーに自動でDMを送信するためのWebインターフェースを提供します。

## 特徴

- 指定したアカウントのフォロワーに自動でDMを送信
- フォロワーの名前をパーソナライズしたメッセージの送信
- 未フォローの場合は自動でフォローしてからDM送信
- DMの送信履歴の管理
- 詳細な実行ログの表示

## 必要条件

- Python 3.7以上
- Flask
- instagrapi

## インストール方法

1. リポジトリをクローンする
```
git clone https://github.com/YOUR-USERNAME/instagram-dm-sender.git
cd instagram-dm-sender
```

2. 依存パッケージをインストールする
```
pip install -r requirements.txt
```

## 使い方

1. アプリケーションを起動する
```
python app.py
```

2. ブラウザで `http://localhost:5000` にアクセスする

3. Instagramのユーザー名、パスワード、ターゲットアカウント、送信するDMメッセージを入力する

4. 「DM送信を開始」ボタンをクリックする

## Renderへのデプロイ

このアプリケーションはRenderにデプロイできます。詳細な手順は以下の通りです：

1. このリポジトリをGitHubにプッシュする
2. Renderでアカウントを作成し、新しいWebサービスを作成する
3. このリポジトリを選択し、以下の設定を行う:
   - Environment: Python
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn -c gunicorn.conf.py app:app`
4. 環境変数 `SECRET_KEY` を設定する
5. デプロイを開始する

## 注意事項

- Instagramのレート制限に注意してください。短時間に多数のDMを送信すると、アカウントが制限される可能性があります。
- このツールの使用はInstagramの利用規約に違反する可能性があります。自己責任で使用してください。

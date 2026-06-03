# 🚀 阿里云 ECS 部署指南

把劳动法助手部署到阿里云 ECS，对外提供 `https://你的域名` 访问。
架构：`公网 → nginx(80/443) → streamlit(127.0.0.1:8501)`，systemd 保活。

> 适用：CentOS / Alibaba Cloud Linux。Ubuntu 把 `yum` 换成 `apt` 即可。

---

## 0. 前置准备

- 一台 ECS（2核4G 起步，知识图谱加载吃内存）
- **安全组放行**：`80`、`443`（HTTP/HTTPS）。`8501` **不用**对公网开（走 nginx 内部转发更安全）
- 域名一个（可选，但强烈建议，HTTPS 需要它）；先把域名解析（A 记录）指向 ECS 公网 IP

---

## 1. 装系统依赖

```bash
sudo yum install -y git nginx
# Python 3.10+（自带的太老可用 conda 或源码装；这里假设已有 python3.10+）
python3 --version
```

---

## 2. 拉代码 + 装 Python 依赖

```bash
cd /root
git clone https://github.com/jack-xian05/jack-xian-first-ai-project.git ai-test
cd ai-test

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 3. 配置密钥（关键，别提交到 GitHub）

```bash
cp .env.example .env
vim .env
```

填入：
```ini
SILICONFLOW_KEY=你的硅基流动Key
APP_PASSWORD=给网站设个访问口令      # 防止陌生人刷爆你的 API 额度
LAW_API_TOKEN=随便一串随机字符串      # 后端接口鉴权（用 law_api 时）
```

> `.env` 已被 `.gitignore` 忽略，不会进仓库，安全。

---

## 4. 知识图谱数据（⚠️ 最容易踩的坑）

`lightrag_store/`（已建好的图谱）**被 `.gitignore` 忽略了**，所以 `git clone` 下来的服务器上**没有这个目录**，直接启动会报"知识图谱尚未构建"。二选一：

**方案 A：把本地建好的图谱上传上去（推荐，省钱省时）**
在你**本地电脑**执行（不是 ECS）：
```bash
# Windows PowerShell / 任意带 scp 的终端
scp -r ./lightrag_store root@你的ECS_IP:/root/ai-test/
```

**方案 B：在服务器上重新构建（会消耗 API 额度，约几分钟）**
```bash
source .venv/bin/activate
python build_graph.py
```

---

## 5. 配 systemd 常驻（关 SSH 也不掉线）

```bash
# 先按需修改 deploy/law-app.service 里的 User / 路径
sudo cp deploy/law-app.service /etc/systemd/system/law-app.service
sudo systemctl daemon-reload
sudo systemctl enable law-app     # 开机自启
sudo systemctl start law-app      # 启动
sudo systemctl status law-app     # 确认 active (running)
journalctl -u law-app -f          # 看实时日志（首次会加载图谱，等几秒）
```

此时本机 `curl http://127.0.0.1:8501` 应能通。

---

## 6. 配 nginx 反向代理

```bash
# 先把 deploy/nginx-law-app.conf 里的 your-domain.com 改成你的域名
sudo cp deploy/nginx-law-app.conf /etc/nginx/conf.d/law-app.conf
sudo nginx -t                     # 测试语法
sudo systemctl enable nginx
sudo systemctl reload nginx
```

现在浏览器访问 `http://你的域名` 应该能看到网站（先输你设的访问口令）。

---

## 7. 上 HTTPS（免费证书）

```bash
sudo yum install -y certbot python3-certbot-nginx
sudo certbot --nginx -d 你的域名
# 按提示填邮箱、同意条款，选自动把 http 重定向到 https
```

完成后访问 `https://你的域名`，地址栏带锁 🔒。certbot 会自动续期。

---

## 8. 日常更新代码

```bash
cd /root/ai-test
git pull
source .venv/bin/activate
pip install -r requirements.txt   # 依赖有变才需要
sudo systemctl restart law-app    # 重启生效
```

---

## 9. 安全清单（公网部署务必检查）

- [x] `.env` 不在 Git 里（已 gitignore）
- [x] 设了 `APP_PASSWORD`，陌生人进不来、刷不了额度
- [x] streamlit 只监听 `127.0.0.1`，不直接暴露公网
- [x] 安全组只开 `80/443`，不开 `8501`
- [ ] 硅基流动后台给 Key 设**消费限额**，万一泄露也有上限兜底
- [ ] 定期看 `journalctl -u law-app` 有无异常访问

---

## 常见问题

| 现象 | 原因 / 解决 |
|------|------------|
| 页面一直转圈 / Please wait | nginx 漏了 WebSocket 头（Upgrade/Connection），见 nginx 配置 |
| 提示"知识图谱尚未构建" | `lightrag_store/` 没上传，见第 4 步 |
| 关了 SSH 网站就挂 | 没用 systemd，还在前台 `streamlit run`，见第 5 步 |
| 加载慢 / OOM | ECS 内存不足，升配或加 swap |
| certbot 失败 | 域名没解析到本机 IP，或安全组没开 80 |

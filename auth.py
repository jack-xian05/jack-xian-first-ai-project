"""
Streamlit 访问口令 —— 部署到公网后防止任何人刷爆 API 额度。
Streamlit 没有内置鉴权，这里用 session_state + 口令做一个最简登录门。

用法：在 app 最开头调用 require_password()，没通过就 st.stop() 挡住后面所有内容。
口令存在 config.APP_PASSWORD（来自 .env 或 Streamlit secrets），不在代码里。
"""
import hmac
import streamlit as st
import config


def require_password():
    """口令门。未设置 APP_PASSWORD 时直接放行（本地开发）；设置了则必须输对才放行。"""
    if not config.APP_PASSWORD:          # 没配口令 → 不拦（方便本地）
        return
    if st.session_state.get("_authed"):  # 本会话已通过 → 放行
        return

    st.title("⚖️ 劳动法智能助手")
    st.caption("请输入访问口令")
    pwd = st.text_input("访问口令", type="password", label_visibility="collapsed",
                        placeholder="请输入访问口令")
    if pwd:
        # 用 hmac.compare_digest 做常量时间比较，避免计时侧信道
        if hmac.compare_digest(pwd, config.APP_PASSWORD):
            st.session_state["_authed"] = True
            st.rerun()
        else:
            st.error("口令错误，请重试")
    st.stop()   # 没通过就停在这，后面的 app 内容不会渲染

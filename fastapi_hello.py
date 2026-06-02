"""
FastAPI 入门 —— 第一个后端接口
核心学习点：什么是 API？就是"别人通过网址访问，你的代码返回数据"。
对比 Streamlit：Streamlit 是【页面】，用户用浏览器看；FastAPI 是【接口】，给程序调用。

运行：  py -m uvicorn fastapi_hello:app --reload
然后浏览器打开：
  http://127.0.0.1:8000/          ← 看 hello
  http://127.0.0.1:8000/docs      ← 自动生成的接口文档（FastAPI 最香的地方）
"""
from fastapi import FastAPI

# 创建一个 app，所有接口都挂在它上面
app = FastAPI(title="我的第一个 API")


# @app.get("/") 的意思：当有人访问 "/" 这个网址时，执行下面这个函数
@app.get("/")
def hello():
    return {"message": "你好，这是我的第一个 FastAPI 接口"}


# 带参数的接口：访问 /ask?question=xxx 时，question 自动接收 xxx
@app.get("/ask")
def ask(question: str):
    # 现在先假装回答，下一步再接真正的劳动法 AI
    return {
        "你问的": question,
        "回答": f"（这里以后会接上劳动法 AI，现在先原样返回）你问的是：{question}",
    }

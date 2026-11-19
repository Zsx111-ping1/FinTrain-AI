# FinTrain AI · 金融数据分析师智能岗前实训平台

React + Vite 前端、FastAPI + SQLite 后端。V1.0 包含三道金融 SQL 训练任务、受控 SQL 查询、自动结果评分、分级提示、操作记录和训练报告。使用完全虚构的金融数据。

## Windows 本地运行

需要 Python 3.10+、Node.js 18+、Git。

**终端1：启动后端（PowerShell）**

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload
```

如果 PowerShell 禁止激活脚本，可以不用激活，改用：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

后端健康检查：http://127.0.0.1:8000/api/health
接口文档：http://127.0.0.1:8000/docs

**终端2：启动前端**

```powershell
cd frontend
npm install
npm run dev
```

浏览器打开：http://127.0.0.1:5173

注意：两个终端的 `cd backend` 和 `cd frontend` 都从解压后的项目根目录进入。

## 功能说明

- 三道任务：客户等级分布、各等级成功交易金额、10月低活跃客户识别
- SQL 通过 SQLite 只读连接执行；使用 SQLite authorizer 禁止写入和危险操作，限制查询时长及结果行数
- 与参考 SQL 的列名和结果多重集比较，允许不影响结果的行顺序差异；这是 MVP 的基础评测，不保证涵盖所有业务语义等价情况
- 规则提示三级；当前没有接入真实大模型，界面上的“AI导师”是预设分层指导
- 训练报告是任务完成度统计，不是经验证的能力模型
- 本地单人演示使用固定 session_id=demo，暂不提供用户认证、隔离和生产级部署

## 双人协作

1. 一人创建 GitHub 私有仓库，邀请另一人为协作者。
2. 成员A创建 `feature/frontend` 分支，主要修改 `frontend/`。
3. 成员B创建 `feature/backend` 分支，主要修改 `backend/`。
4. 各自提交、推送分支并创建 Pull Request；互相审查后合并到 `main`。
5. 合并后两人都运行全流程：选择任务 → 写 SQL → 运行 → 获取提示 → 查看报告。

## 版本升级建议

V1.1：加入 Monaco Editor、用户登录、任务进度持久化、图表类型选择。
V1.2：在后端接入大模型 API，基于错误类型和操作日志生成提示，保护 API Key。
V2.0：实现任务难度动态调整、能力画像、对照实验与更完整的金融业务案例。

## 安全边界

此项目仅用于本地教学演示。虽然有只读授权与超时限制，但没有生产级沙箱隔离、认证、访问限流和审计，不应将当前 SQL 执行接口直接暴露到公网。

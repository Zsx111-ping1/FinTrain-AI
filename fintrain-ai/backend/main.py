from __future__ import annotations
import json
import re
import sqlite3
import time
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).parent
DB = ROOT / 'training.db'
app = FastAPI(title='FinTrain AI API', version='1.0')
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173','http://127.0.0.1:5173'], allow_methods=['*'], allow_headers=['*'])

TASKS = [
 {'id':1,'title':'客户等级分布','difficulty':'基础','description':'统计每个客户等级的人数，返回 customer_level 和 total 两列。','skills':['GROUP BY','COUNT'],'reference':'SELECT customer_level, COUNT(*) AS total FROM customers GROUP BY customer_level'},
 {'id':2,'title':'各等级交易金额','difficulty':'进阶','description':'统计各客户等级成功交易的总金额，返回 customer_level 和 total_amount 两列，按金额从高到低排序。','skills':['JOIN','SUM','GROUP BY'],'reference':"SELECT c.customer_level, ROUND(SUM(t.amount), 2) AS total_amount FROM customers c JOIN transactions t ON c.customer_id=t.customer_id WHERE t.status='success' GROUP BY c.customer_level ORDER BY total_amount DESC"},
 {'id':3,'title':'识别低活跃客户','difficulty':'综合','description':'找出2026年10月成功交易次数少于2次的客户，返回 customer_id、customer_name、tx_count 三列，按 customer_id 升序排列（包含零交易客户）。','skills':['LEFT JOIN','日期过滤','HAVING'],'reference':"SELECT c.customer_id, c.customer_name, COUNT(t.transaction_id) AS tx_count FROM customers c LEFT JOIN transactions t ON c.customer_id=t.customer_id AND t.status='success' AND t.transaction_date >= '2026-10-01' AND t.transaction_date < '2026-11-01' GROUP BY c.customer_id,c.customer_name HAVING COUNT(t.transaction_id)<2 ORDER BY c.customer_id"}
]

class SQLRequest(BaseModel):
    task_id: int
    sql: str = Field(min_length=1,max_length=5000)
    session_id: str = Field(default='demo', min_length=1,max_length=64,pattern=r'^[a-zA-Z0-9_-]+$')

class HintRequest(BaseModel):
    task_id: int
    level: int = Field(ge=1,le=3)
    session_id: str = Field(default='demo', min_length=1,max_length=64,pattern=r'^[a-zA-Z0-9_-]+$')

HINTS = {
 1:['思考应该按哪个字段分组。','使用 GROUP BY customer_level，再考虑计数函数。','尝试 SELECT customer_level, COUNT(*) AS total FROM customers GROUP BY customer_level。'],
 2:['交易金额在 transactions 表中，客户等级在 customers 表中。','用 customer_id 连接两张表，只统计 success 状态。','考虑 JOIN、WHERE status=success、SUM(amount)、GROUP BY。'],
 3:['注意零交易客户也要包含在结果中。','尝试 LEFT JOIN，把日期和状态条件放到 ON 中。','用 COUNT(t.transaction_id) 和 HAVING 过滤小于2次的客户。']
}

def connect(readonly=False):
    if readonly:
        conn = sqlite3.connect(f'file:{DB.as_posix()}?mode=ro',uri=True,timeout=1)
        conn.execute('PRAGMA query_only=ON')
    else:
        conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with closing(connect()) as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS customers(customer_id INTEGER PRIMARY KEY,customer_name TEXT,customer_level TEXT,city TEXT);
        CREATE TABLE IF NOT EXISTS transactions(transaction_id INTEGER PRIMARY KEY,customer_id INTEGER,amount REAL,status TEXT,transaction_date TEXT);
        CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT,task_id INTEGER,sql_text TEXT,correct INTEGER,error TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS hints(id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT,task_id INTEGER,level INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')
        if conn.execute('SELECT COUNT(*) FROM customers').fetchone()[0]==0:
            conn.executemany('INSERT INTO customers VALUES(?,?,?,?)',[
                (1,'客户甲','普通','成都'),(2,'客户乙','金卡','北京'),(3,'客户丙','银卡','成都'),(4,'客户丁','普通','上海'),(5,'客户戊','金卡','成都'),(6,'客户己','银卡','杭州'),(7,'客户庚','普通','北京'),(8,'客户辛','银卡','上海')])
            conn.executemany('INSERT INTO transactions VALUES(?,?,?,?,?)',[
                (1,1,120,'success','2026-10-02'),(2,1,80,'success','2026-10-12'),(3,2,1200,'success','2026-10-03'),(4,2,500,'success','2026-10-15'),(5,2,100,'failed','2026-10-19'),(6,3,300,'success','2026-10-07'),(7,4,40,'success','2026-09-20'),(8,5,1800,'success','2026-10-08'),(9,5,900,'success','2026-10-18'),(10,6,220,'success','2026-10-22'),(11,7,60,'failed','2026-10-05'),(12,8,350,'success','2026-10-03'),(13,8,200,'success','2026-10-29')])
        conn.commit()

init_db()

# Restrict to read-only SQL even when a user embeds comments, CTEs, PRAGMA, or multiple statements.
READ_ACTIONS = {sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION}

def safe_query(sql: str):
    if len(sql)>5000 or not re.match(r'^\s*(SELECT|WITH)\b',sql,re.I):
        raise ValueError('仅允许 SELECT 或只读 WITH 查询。')
    with closing(connect(readonly=True)) as conn:
        def authorize(action,arg1,arg2,db_name,source):
            return sqlite3.SQLITE_OK if action in READ_ACTIONS else sqlite3.SQLITE_DENY
        conn.set_authorizer(authorize)
        deadline=time.monotonic()+1.0
        conn.set_progress_handler(lambda: 1 if time.monotonic()>deadline else 0,1000)
        try:
            cur=conn.execute(sql)
            columns=[d[0] for d in cur.description or []]
            if not columns: raise ValueError('查询没有返回列。')
            rows=[list(r) for r in cur.fetchmany(201)]
            if len(rows)>200: raise ValueError('结果超过200行，请增加过滤条件。')
            return {'columns':columns,'rows':rows}
        except sqlite3.Error as exc:
            raise ValueError(f'SQL执行失败：{exc}') from exc

def normalized(result):
    # Reference queries use stable output aliases; ordering is ignored for scoring.
    def norm_value(x):
        return round(x,6) if isinstance(x,float) else x
    return Counter(tuple(norm_value(v) for v in row) for row in result['rows'])

@app.get('/api/health')
def health(): return {'status':'ok'}

@app.get('/api/tasks')
def tasks(): return [{k:v for k,v in t.items() if k!='reference'} for t in TASKS]

@app.get('/api/schema')
def schema(): return {'customers':['customer_id','customer_name','customer_level','city'],'transactions':['transaction_id','customer_id','amount','status','transaction_date']}

@app.post('/api/run')
def run(req:SQLRequest):
    task=next((t for t in TASKS if t['id']==req.task_id),None)
    if not task: raise HTTPException(404,'任务不存在')
    try:
        result=safe_query(req.sql)
        reference=safe_query(task['reference'])
        correct=(result['columns']==reference['columns'] and normalized(result)==normalized(reference))
        error=None
    except ValueError as exc:
        result={'columns':[],'rows':[]};correct=False;error=str(exc)
    with closing(connect()) as conn:
        conn.execute('INSERT INTO attempts(session_id,task_id,sql_text,correct,error) VALUES(?,?,?,?,?)',(req.session_id,req.task_id,req.sql,int(correct),error))
        conn.commit()
    return {'result':result,'correct':correct,'error':error,'feedback':('查询正确，结果与标准答案一致。' if correct else ('请检查SQL语法或业务统计口径。' if not error else error))}

@app.post('/api/hint')
def hint(req:HintRequest):
    if req.task_id not in HINTS: raise HTTPException(404,'任务不存在')
    with closing(connect()) as conn:
        conn.execute('INSERT INTO hints(session_id,task_id,level) VALUES(?,?,?)',(req.session_id,req.task_id,req.level));conn.commit()
    return {'hint':HINTS[req.task_id][req.level-1]}

@app.get('/api/report/{session_id}')
def report(session_id:str):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',session_id):raise HTTPException(400,'无效会话ID')
    with closing(connect()) as conn:
        attempts=conn.execute('SELECT task_id,correct,error FROM attempts WHERE session_id=? ORDER BY id',(session_id,)).fetchall()
        hints=conn.execute('SELECT task_id,COUNT(*) AS n FROM hints WHERE session_id=? GROUP BY task_id',(session_id,)).fetchall()
    hints_by={r['task_id']:r['n'] for r in hints}
    completed=sorted({r['task_id'] for r in attempts if r['correct']})
    errors=sum(bool(r['error']) for r in attempts)
    score=round(100*len(completed)/len(TASKS))
    advice='优先练习 SQL 基础查询与分组统计。' if 1 not in completed else ('重点加强多表关联与业务指标计算。' if 2 not in completed else ('进一步练习 LEFT JOIN 与低活跃用户识别。' if 3 not in completed else '全部任务已完成，可以挑战更复杂的业务案例。'))
    return {'completed':completed,'attempts':len(attempts),'syntax_errors':errors,'hints_used':sum(hints_by.values()),'score':score,'advice':advice,'note':'当前为任务完成度评分，并非经验证的综合能力测评。'}

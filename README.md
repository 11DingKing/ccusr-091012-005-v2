# 监管物资保管服务

该项目为监管仓、证物室和受控物资保管点提供服务端 API，覆盖人员授权、物资分类、批次登记、收发记录、审批、预警、审计日志与统计报表。数据保存在 SQLite，所有测试和接口验收均可在单个 Linux 应用容器内离线完成。

## 运行环境

- Python 3.11
- Django REST Framework
- SQLite

## 安装与初始化

```bash
python -m pip install -r backend/requirements.txt
cd backend
python manage.py migrate --run-syncdb
```

## 测试

```bash
cd backend
pytest -q
```

## 编译检查

```bash
python -m compileall -q backend
```

## API 验收

```bash
cd backend
python manage.py migrate --run-syncdb
python manage.py shell -c "from rest_framework.test import APIClient; from apps.authentication.models import User; u=User.objects.create_user('smoke','safe-pass',role='admin'); c=APIClient(); r=c.post('/api/auth/login/',{'username':'smoke','password':'safe-pass'},format='json'); print(r.status_code, bool(r.json()['data']['token']))"
```

## 隔离处置

入库检查发现包装破损等异常时，建立隔离处置案件，把发现原因、影响数量、复检记录、
审批意见与最终库存移动串成一条可追溯流程，替代过去“改位置 + 写备注”的做法。

- 建案即冻结：影响数量从可用库存中划入隔离数量，生成首条“隔离入库”流水。
- 复检与处置：案件下可登记多条复检记录；处置决定（放行 / 让步接收 / 退回 / 销毁）
  需审批通过后才会执行库存移动，审批意见随流水留痕。
- 部分放行：按数量分批处置，剩余数量继续保持隔离，案件在全部处置完后自动结案。
- 撤销不删历史：撤销已执行的决定会生成一笔反向流水（指向被冲销的流水），
  库存与案件数量相应回滚，原决定与流水全部保留。
- 并发阻断：领用与库位转移在数据库层原子校验，遇到有效隔离数量时被阻断，
  并发请求不会击穿冻结。
- 案件页对账：详情接口返回数量去向汇总（放行 / 退回 / 销毁 / 仍隔离），
  每一数量单位的当前处置状态均可核对。

### 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/api/quarantine-cases/` | 案件列表 / 建立案件 |
| GET | `/api/quarantine-cases/<id>/` | 案件详情（复检、决定、流水、数量去向） |
| POST | `/api/quarantine-cases/<id>/inspections/` | 登记复检记录 |
| POST | `/api/quarantine-cases/<id>/decisions/` | 提出处置决定 |
| GET | `/api/quarantine-decisions/` | 处置决定列表 |
| POST | `/api/quarantine-decisions/<id>/review/` | 审批决定（`approve` + `opinion`） |
| POST | `/api/quarantine-decisions/<id>/revoke/` | 撤销已执行决定（生成反向流水） |
| GET/POST | `/api/stock-in/` | 入库记录 / 入库登记 |
| GET/POST | `/api/stock-out/` | 出库记录 / 领用登记（遇有效隔离阻断） |
| POST | `/api/goods/<id>/transfer/` | 库位转移（遇有效隔离阻断） |

## 容器

```bash
docker build -t custody-service .
docker run --rm custody-service
```

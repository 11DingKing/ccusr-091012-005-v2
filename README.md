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

## 容器

```bash
docker build -t custody-service .
docker run --rm custody-service
```

## 隔离处置流程

入库检查发现包装破损等异常时，工作人员通过"隔离处置案件"把整个处置过程串成一条可追溯链路，
不再依赖在备注里手工改库位：

```
立案（发现原因/影响数量） → 移入隔离区并按数量单位拆分处置单元
  → 复检记录（合格/让步/不合格数量）
  → 审批意见（放行 / 让步接收 / 退回）
  → 库存移动（隔离移出 / 退回出库 / 库位转移）
  → 撤销（生成反向动作，历史永不删除）
```

关键规则：

- 影响数量按数量单位（整数件）拆成处置单元，案件页返回**每一单位的当前处置状态**
  （隔离中 / 部分处置中（剩余隔离） / 已放行 / 让步接收 / 已退回）。
- 部分放行或让步后，**剩余数量仍保持有效隔离**，案件不结案。
- 并发领用（`/api/stock-out/`）或转移（`/api/stock-movements/transfer/`）触碰有效隔离时
  返回 `409`；已审批但未出库的领用在出库执行瞬间再次校验，隔离后立案同样阻断。
- 撤销审批决定生成 REVERSAL 反向移动并把数量退回有效隔离；退回出库的撤销反向补回库存；
  放行后已被领用消耗的数量不允许撤销。
- 撤销案件（仅限无处置决定的误立案）反向冲销"移入隔离区"动作并恢复原库位。

接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/api/quarantine-cases/` | 案件列表 / 立案 |
| GET/DELETE | `/api/quarantine-cases/<id>/` | 案件全链路详情（单元、复检、审批、移动）/ 撤销案件 |
| POST | `/api/quarantine-cases/<id>/reinspection/` | 登记复检记录 |
| POST | `/api/quarantine-cases/<id>/decision/` | 提交审批决定并生成库存移动 |
| POST | `/api/quarantine-approvals/<id>/revoke/` | 撤销决定（反向动作） |
| GET/POST | `/api/stock-out/` | 领用记录 / 发起领用（受隔离阻断） |
| POST | `/api/stock-out/<id>/complete/` | 领用出库执行（出库瞬间再校验隔离） |
| POST | `/api/stock-movements/transfer/` | 库位转移（受隔离阻断） |

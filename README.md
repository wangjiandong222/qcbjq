# 12345 涉检线索智能筛查工具

面向政法机关的 12345 市民热线涉检线索智能筛查原型系统。系统围绕“数据导入、工单检索、公益成案领域筛查、弱势群体筛查、行政违法识别、重复事件聚合、预警研判、人工确认、材料导出、审计留痕”形成完整工作闭环。

## 技术栈

- 前端：React + TypeScript + Vite
- 后端：FastAPI + SQLAlchemy + SQLite
- 数据处理：openpyxl
- 智能筛查：本地规则引擎，预留大模型适配器

## 项目目录

```text
backend/    FastAPI 后端服务、SQLite 数据库模型、导入筛查导出逻辑
frontend/   React + TypeScript + Vite 前端工作台
docs/       运行手册、安全设计等项目文档
scripts/    本地初始化和启动脚本
```

> 说明：本仓库不包含本地数据库、原始 Excel、导出 Excel、依赖目录和构建产物。真实或模拟数据请在系统页面中手动上传。

## 快速启动：推荐方式

当前版本推荐使用“后端 8000 + 前端 5173”的本地启动方式。需要打开两个终端。

### 1. 启动后端

```bash
cd /Users/wang/Desktop/青创北京
bash scripts/start_backend.sh
```

后端地址：

```text
http://127.0.0.1:8000
```

健康检查：

```text
http://127.0.0.1:8000/api/health
```

### 2. 启动前端

```bash
cd /Users/wang/Desktop/青创北京
bash scripts/start_frontend.sh
```

前端访问：

```text
http://127.0.0.1:5173
```

如果 `http://127.0.0.1:5173/api/health` 也能返回后端健康检查结果，说明前端代理正常。

## 演示账号

| 账号 | 密码 | 权限 |
|---|---|---|
| `admin` | `admin123` | 全部权限 |
| `prosecutor` | `prosecutor123` | 查看、筛查、复核、导出 |
| `reviewer` | `reviewer123` | 查看、复核 |
| `viewer` | `viewer123` | 只读 |

这些账号仅用于本地演示，上线前必须更换默认密码和 `SECRET_KEY`。

## 核心功能

- 数据导入是第一个业务板块，系统初始化后不自动导入数据，支持多个 Excel 批次并存。
- 用户手动上传 Excel 后不会替换旧批次；可勾选批次运行公益成案领域、弱势群体、行政违法筛查，也可删除选中批次。
- 系统按 Excel 表头映射标准字段，缺列自动为空，多出的列会保存在详情和导出中；展示、导出、模型调用均保留原始数据，不做脱敏。
- 公益成案领域、弱势群体、行政违法均按线索标注规则生成分类结果，未命中规则的数据进入“未知领域”或“其他”。
- “线索标注”独立维护，支持按板块新增、编辑、删除和启停，规则变更后重新运行筛查即可更新待确认分类结果。
- “预警研判”统一承载屡诉未决、预警中心、履职异常与趋势分析，围绕“长期存在、多次反映、仍未解决”输出介入建议。
- 工单库支持按标题、正文、问题分类、工单编号等字段进行关键词检索或语义检索；拖欠工资类数据可导出“核心内容提炼”。
- 根据未解决、不满意、公共安全、投诉频次生成风险等级。
- 各业务页面右上角提供选择导出和去除已导出筛选，导出成功后工单全局标记为已导出。
- 登录、查看详情、导入、筛查、复核、导出均写入审计日志。

## 数据导入说明

系统不会自动导入样例数据。登录后进入“数据导入”页面，手动上传 Excel。导入逻辑按 Excel 表头映射字段，缺列自动留空，多出的列会作为额外字段保留在详情和导出中。

由于项目面向政法机关，GitHub 仓库已排除以下本地文件：

- `qingchuang.db`
- `data/raw/`
- `data/exports/`
- `frontend/node_modules/`
- `backend/.venv/`
- `frontend/dist/`

请不要把真实 12345 原始数据提交到公开仓库。

## 大模型配置

默认不启用外部模型。后端提供 `LLMAdapter`，按 OpenAI-compatible 方式预留：

```env
LLM_ENABLED=true
LLM_BASE_URL=https://example.com/v1
LLM_API_KEY=your-key
LLM_MODEL=your-model
```

当前版本按业务要求使用原始工单内容进行模型增强。政法机关部署建议优先使用私有化或专有云模型，并在启用外部模型前完成数据出域审批。

## 常用命令

```bash
# 后端测试
cd /Users/wang/Desktop/青创北京/backend
.venv/bin/python -m pytest tests/test_services.py -q

# 前端构建
cd /Users/wang/Desktop/青创北京/frontend
npm run build
```

## GitHub 提醒

当前仓库用于代码和文档管理。若继续用于政法机关项目展示或真实数据试点，建议在 GitHub 仓库设置中改为 Private，避免项目细节被公开检索。

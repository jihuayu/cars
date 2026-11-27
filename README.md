# 国产新能源车官方参数配置库（SKU JSON）

截至 **2026-11-26** 的国产新能源主流品牌在售主力车型逐 SKU 结构化参数配置数据，优先采集自各厂商官网参数配置表及官方发布公告。

## 数据规模总览

<!-- STATS:START -->
共收录 **50 大品牌（国产 27 + 合资/外资 13） / 231 款在售主力车型 / 865 个 SKU**（数据更新日期：**2026-11-27**），在线预览见 **[GitHub Pages 车型配置展厅](https://jihuayu.github.io/cars/)**，全量索引见 [`index.json`](./index.json)，数据结构定义见 [`schema.json`](./schema.json)。

| 厂商目录 | 品牌 | 产地类型 | 车型数 | SKU 数 | 品牌索引 |
| :--- | :--- | :--- | ---: | ---: | :--- |
| `data/lixiang/` | 理想汽车 | 国产 | 7 | 11 | [`data/lixiang/index.json`](./data/lixiang/index.json) |
| `data/xiaopeng/` | 小鹏汽车 | 国产 | 8 | 40 | [`data/xiaopeng/index.json`](./data/xiaopeng/index.json) |
| `data/avatr/` | 阿维塔 | 国产 | 6 | 28 | [`data/avatr/index.json`](./data/avatr/index.json) |
| `data/nio/` | 蔚来 | 国产 | 7 | 24 | [`data/nio/index.json`](./data/nio/index.json) |
| `data/onvo/` | 乐道 | 国产 | 3 | 14 | [`data/onvo/index.json`](./data/onvo/index.json) |
| `data/firefly/` | 萤火虫 | 国产 | 1 | 6 | [`data/firefly/index.json`](./data/firefly/index.json) |
| `data/leapmotor/` | 零跑汽车 | 国产 | 8 | 49 | [`data/leapmotor/index.json`](./data/leapmotor/index.json) |
| `data/immotors/` | 智己汽车 | 国产 | 5 | 23 | [`data/immotors/index.json`](./data/immotors/index.json) |
| `data/hima/` | 鸿蒙智行 | 国产 | 15 | 87 | [`data/hima/index.json`](./data/hima/index.json) |
| `data/xiaomi/` | 小米汽车 | 国产 | 4 | 14 | [`data/xiaomi/index.json`](./data/xiaomi/index.json) |
| `data/zeekr/` | 极氪 | 国产 | 6 | 28 | [`data/zeekr/index.json`](./data/zeekr/index.json) |
| `data/lynkco/` | 领克新能源 | 国产 | 3 | 13 | [`data/lynkco/index.json`](./data/lynkco/index.json) |
| `data/byd/` | 比亚迪 | 国产 | 16 | 76 | [`data/byd/index.json`](./data/byd/index.json) |
| `data/denza/` | 腾势 | 国产 | 4 | 21 | [`data/denza/index.json`](./data/denza/index.json) |
| `data/fangchengbao/` | 方程豹 | 国产 | 4 | 17 | [`data/fangchengbao/index.json`](./data/fangchengbao/index.json) |
| `data/yangwang/` | 仰望 | 国产 | 3 | 10 | [`data/yangwang/index.json`](./data/yangwang/index.json) |
| `data/voyah/` | 岚图 | 国产 | 5 | 21 | [`data/voyah/index.json`](./data/voyah/index.json) |
| `data/deepal/` | 深蓝 | 国产 | 5 | 25 | [`data/deepal/index.json`](./data/deepal/index.json) |
| `data/geely-galaxy/` | 吉利银河 | 国产 | 8 | 34 | [`data/geely-galaxy/index.json`](./data/geely-galaxy/index.json) |
| `data/changan-qiyuan/` | 长安启源 | 国产 | 3 | 14 | [`data/changan-qiyuan/index.json`](./data/changan-qiyuan/index.json) |
| `data/exeed-sterra/` | 星途星纪元 | 国产 | 2 | 9 | [`data/exeed-sterra/index.json`](./data/exeed-sterra/index.json) |
| `data/icar/` | iCAR | 国产 | 2 | 9 | [`data/icar/index.json`](./data/icar/index.json) |
| `data/hyptec/` | 广汽昊铂 | 国产 | 3 | 13 | [`data/hyptec/index.json`](./data/hyptec/index.json) |
| `data/aion/` | 广汽埃安 | 国产 | 3 | 10 | [`data/aion/index.json`](./data/aion/index.json) |
| `data/arcfox/` | 极狐 | 国产 | 4 | 15 | [`data/arcfox/index.json`](./data/arcfox/index.json) |
| `data/wey/` | 魏牌 | 国产 | 2 | 8 | [`data/wey/index.json`](./data/wey/index.json) |
| `data/tank/` | 坦克新能源 | 国产 | 2 | 6 | [`data/tank/index.json`](./data/tank/index.json) |
| `data/wuling/` | 五菱 / 宝骏 | 国产 | 6 | 22 | [`data/wuling/index.json`](./data/wuling/index.json) |
| `data/chery-fulwin/` | 奇瑞风云 / 捷途山海 | 国产 | 8 | 28 | [`data/chery-fulwin/index.json`](./data/chery-fulwin/index.json) |
| `data/gwm-haval-ora/` | 哈弗新能源 / 欧拉 | 国产 | 4 | 14 | [`data/gwm-haval-ora/index.json`](./data/gwm-haval-ora/index.json) |
| `data/hongqi/` | 红旗新能源 | 国产 | 5 | 16 | [`data/hongqi/index.json`](./data/hongqi/index.json) |
| `data/dongfeng-epai/` | 东风奕派 / 纳米 / 猛士 | 国产 | 5 | 17 | [`data/dongfeng-epai/index.json`](./data/dongfeng-epai/index.json) |
| `data/saic-roewe-mg/` | 荣威 / MG新能源 | 国产 | 4 | 14 | [`data/saic-roewe-mg/index.json`](./data/saic-roewe-mg/index.json) |
| `data/other-domestic/` | 极石 / 江淮钇为 / 北京越野 | 国产 | 3 | 11 | [`data/other-domestic/index.json`](./data/other-domestic/index.json) |
| `data/tesla/` | 特斯拉 | 合资/外资 | 5 | 11 | [`data/tesla/index.json`](./data/tesla/index.json) |
| `data/bmw/` | 宝马新能源 | 合资/外资 | 5 | 11 | [`data/bmw/index.json`](./data/bmw/index.json) |
| `data/mercedes/` | 奔驰新能源 | 合资/外资 | 5 | 8 | [`data/mercedes/index.json`](./data/mercedes/index.json) |
| `data/audi/` | 奥迪新能源 | 合资/外资 | 4 | 8 | [`data/audi/index.json`](./data/audi/index.json) |
| `data/porsche/` | 保时捷新能源 | 合资/外资 | 2 | 4 | [`data/porsche/index.json`](./data/porsche/index.json) |
| `data/volvo/` | 沃尔沃/极星 | 合资/外资 | 5 | 9 | [`data/volvo/index.json`](./data/volvo/index.json) |
| `data/volkswagen/` | 大众新能源 | 合资/外资 | 5 | 10 | [`data/volkswagen/index.json`](./data/volkswagen/index.json) |
| `data/toyota/` | 丰田新能源 | 合资/外资 | 4 | 8 | [`data/toyota/index.json`](./data/toyota/index.json) |
| `data/honda/` | 本田新能源 | 合资/外资 | 2 | 4 | [`data/honda/index.json`](./data/honda/index.json) |
| `data/nissan/` | 日产新能源 | 合资/外资 | 2 | 4 | [`data/nissan/index.json`](./data/nissan/index.json) |
| `data/gm/` | 通用新能源 | 合资/外资 | 5 | 10 | [`data/gm/index.json`](./data/gm/index.json) |
| `data/smart/` | smart | 合资/外资 | 3 | 6 | [`data/smart/index.json`](./data/smart/index.json) |
| `data/kia-hyundai/` | 起亚 / 现代新能源 | 合资/外资 | 2 | 5 | [`data/kia-hyundai/index.json`](./data/kia-hyundai/index.json) |
| `data/mini/` | 电动MINI | 合资/外资 | 2 | 5 | [`data/mini/index.json`](./data/mini/index.json) |
| `data/lotus/` | 莲花跑车 / 路特斯 | 合资/外资 | 2 | 7 | [`data/lotus/index.json`](./data/lotus/index.json) |
| `data/joint-other/` | 马自达/福特/雷克萨斯 | 合资/外资 | 4 | 8 | [`data/joint-other/index.json`](./data/joint-other/index.json) |
<!-- STATS:END -->

## 目录结构

```text
.
├── .github/workflows/
│   ├── validate.yml             # Push / PR 自动校验 JSON Schema 与索引一致性
│   └── auto-update.yml          # 每周一自动巡检官网配置页并提 PR（支持手动触发）
├── scripts/
│   ├── validate_and_index.py    # 零依赖 JSON 校验与 index.json / README 自动重建
│   └── sync_official.py         # 官网配置页巡检、无损补全与变更报告生成（HTTP + Playwright）
├── README.md
├── requirements.txt
├── schema.json                  # 统一 JSON Schema 定义
├── index.json                   # 全量品牌与车型汇总索引
└── data/
    ├── lixiang/                 # 理想汽车（L6 / L8 / L9 / i6 / i8 / i9 / MEGA）
    ├── xiaopeng/                # 小鹏汽车（MONA M03 / P7 / P7+ / G6 / G7 / G9 / X9 / GX）
    ├── avatr/                   # 阿维塔（06 / 06T / 07 / 07L / 11 / 12）
    ├── nio/                     # 蔚来（ET5 / ET5T / ES6 / EC6 / ES8 / ES9 / ET9）
    ├── leapmotor/               # 零跑汽车（B10 / B01 / C10 / C11 / C16 / Lafa5 / D19 / D99）
    ├── immotors/                # 智己汽车（L6 / LS6 / LS8 / LS9 / LS7）
    └── hima/                    # 鸿蒙智行（问界 / 智界 / 享界 / 尊界 / 尚界）
```

## 本地更新与校验

```bash
# 1. 仅校验全部 JSON 与索引一致性（零外部依赖）
python3 scripts/validate_and_index.py --check

# 2. 手动修改 data/ 后重建所有 index.json 与 README 统计表
python3 scripts/validate_and_index.py

# 3. 巡检官网配置页（安装依赖后支持 Playwright 渲染 SPA 页面）
pip install -r requirements.txt
python3 -m playwright install chromium
python3 scripts/sync_official.py --browser --write-report sync_report.md
```

## GitHub Actions 自动更新

- **自动校验**（`.github/workflows/validate.yml`）：每次 `push` 或 `pull_request` 自动执行 `validate_and_index.py --check`，防止 JSON 语法错误、`sku_id` 重复或索引未同步。
- **定时同步**（`.github/workflows/auto-update.yml`）：每周一北京时间 10:00 自动运行 Playwright + HTTP 巡检全部车型 `source_urls`，生成变更报告 `sync_report.md`，默认自动创建 PR 供审核（手动 `workflow_dispatch` 时可按品牌筛选，也可勾选 `commit_directly` 直接推送到 `main`）。

> **提示**：如仓库首次使用 `create-pull-request` 自动创建 PR，请在 GitHub 仓库 `Settings -> Actions -> General -> Workflow permissions` 中开启 **Allow GitHub Actions to create and approve pull requests**。

## 单 SKU 核心字段说明

每个车型文件 `data/<brand>/<model_slug>.json` 内包含 `skus` 数组，每个 SKU 对象包含：

- **基础信息**：`sku_id`、`sku_name`、`price_rmb`（官方指导价）、`baas_price_rmb`（蔚来 BaaS 起售价）、`powertrain_type`（`BEV` / `REEV`）
- **尺寸空间 (`dimensions`)**：长/宽/高（mm）、轴距（mm）、座位数、整备质量（kg）、后备厢/前备厢容积（L）、最小转弯半径（m）、风阻系数（Cd）
- **动力性能 (`performance`)**：驱动形式、电机总功率（kW）、总扭矩（N·m）、0–100 km/h 加速（s）、最高车速（km/h）
- **三电与补能 (`battery_and_charging`)**：高压平台（V）、电池类型与供应商、电池容量（kWh）、CLTC 纯电/综合续航（km）、电耗、快充倍率与时长、外放电功率（kW）、换电支持、油箱容积与亏电油耗
- **底盘悬架 (`chassis`)**：前/后悬架、空气悬架、CDC 可变阻尼、后轮转向、线控转向、轮毂轮胎规格
- **智驾与座舱 (`adas` / `cockpit`)**：智驾芯片与算力（TOPS）、激光雷达配置、智驾系统与买断/订阅政策、座舱芯片、屏幕、HUD、音响、冰箱、座椅配置
- **选装清单 (`options`)**：各选装项目名称、官方选装价格（元）及包含内容；官方静态配置页未公开的单价以 `null` 标注，不作臆测。

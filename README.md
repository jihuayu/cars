# 国产新能源车官方参数配置库（SKU JSON）

截至 **2026-11-26** 的国产新能源主流品牌在售主力车型逐 SKU 结构化参数配置数据，优先采集自各厂商官网参数配置表及官方发布公告。

## 数据规模总览

共收录 **7 大品牌 / 54 款主力车型 / 248 个在售 SKU**，全量索引见 [`index.json`](./index.json)，数据结构定义见 [`schema.json`](./schema.json)。

| 厂商目录 | 品牌 | 车型数 | SKU 数 | 品牌索引 |
| :--- | :--- | ---: | ---: | :--- |
| `data/lixiang/` | 理想汽车（Li Auto） | 7 | 11 | [`data/lixiang/index.json`](./data/lixiang/index.json) |
| `data/xiaopeng/` | 小鹏汽车（XPeng） | 8 | 40 | [`data/xiaopeng/index.json`](./data/xiaopeng/index.json) |
| `data/avatr/` | 阿维塔（Avatr） | 6 | 28 | [`data/avatr/index.json`](./data/avatr/index.json) |
| `data/nio/` | 蔚来（NIO） | 7 | 24 | [`data/nio/index.json`](./data/nio/index.json) |
| `data/leapmotor/` | 零跑汽车（Leapmotor） | 8 | 49 | [`data/leapmotor/index.json`](./data/leapmotor/index.json) |
| `data/immotors/` | 智己汽车（IM Motors） | 5 | 23 | [`data/immotors/index.json`](./data/immotors/index.json) |
| `data/hima/` | 鸿蒙智行（HIMA） | 13 | 73 | [`data/hima/index.json`](./data/hima/index.json) |

## 目录结构

```text
.
├── README.md
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

## 单 SKU 核心字段说明

每个车型文件 `data/<brand>/<model_slug>.json` 内包含 `skus` 数组，每个 SKU 对象包含：

- **基础信息**：`sku_id`、`sku_name`、`price_rmb`（官方指导价）、`baas_price_rmb`（蔚来 BaaS 起售价）、`powertrain_type`（`BEV` / `REEV`）
- **尺寸空间 (`dimensions`)**：长/宽/高（mm）、轴距（mm）、座位数、整备质量（kg）、后备厢/前备厢容积（L）、最小转弯半径（m）、风阻系数（Cd）
- **动力性能 (`performance`)**：驱动形式、电机总功率（kW）、总扭矩（N·m）、0–100 km/h 加速（s）、最高车速（km/h）
- **三电与补能 (`battery_and_charging`)**：高压平台（V）、电池类型与供应商、电池容量（kWh）、CLTC 纯电/综合续航（km）、电耗、快充倍率与时长、外放电功率（kW）、换电支持、油箱容积与亏电油耗
- **底盘悬架 (`chassis`)**：前/后悬架、空气悬架、CDC 可变阻尼、后轮转向、线控转向、轮毂轮胎规格
- **智驾与座舱 (`adas` / `cockpit`)**：智驾芯片与算力（TOPS）、激光雷达配置、智驾系统与买断/订阅政策、座舱芯片、屏幕、HUD、音响、冰箱、座椅配置
- **选装清单 (`options`)**：各选装项目名称、官方选装价格（元）及包含内容；官方静态配置页未公开的单价以 `null` 标注，不作臆测。

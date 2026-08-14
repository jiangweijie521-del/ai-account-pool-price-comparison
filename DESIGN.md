---
name: 库存比价台
description: 一张自动更新、最低价优先的无障碍库存票据
colors:
  cobalt-stamp: "#0b45c7"
  cobalt-deep: "#072f8d"
  safety-yellow: "#ffe11a"
  safety-yellow-soft: "#fff7a7"
  receipt-paper: "#ffffff"
  cool-canvas: "#e9eef3"
  black-ink: "#0b0d10"
  muted-ink: "#4a5260"
  ledger-line: "#1a1d22"
  soft-line: "#b7bec8"
  success-ink: "#0b5b32"
  warning-ink: "#815300"
  danger-ink: "#a11c1c"
typography:
  display:
    fontFamily: "Segoe UI Variable, Microsoft YaHei UI, PingFang SC, sans-serif"
    fontSize: "4.8rem desktop / 3rem mobile"
    fontWeight: 700
    lineHeight: 0.98
    letterSpacing: "0"
  body:
    fontFamily: "Segoe UI Variable, Microsoft YaHei UI, PingFang SC, sans-serif"
    fontSize: "18px"
    fontWeight: 400
    lineHeight: 1.55
  data:
    fontFamily: "Bahnschrift, Segoe UI Variable, Microsoft YaHei UI, sans-serif"
    fontSize: "1.2rem"
    fontWeight: 800
    lineHeight: 1.2
rounded:
  field: "3px"
  control: "4px"
spacing:
  xs: "5px"
  sm: "8px"
  md: "14px"
  lg: "24px"
  section: "30px"
components:
  button-primary:
    backgroundColor: "{colors.cobalt-stamp}"
    textColor: "{colors.receipt-paper}"
    rounded: "{rounded.control}"
    padding: "12px 18px"
    height: "72px"
  button-secondary:
    backgroundColor: "{colors.receipt-paper}"
    textColor: "{colors.cobalt-deep}"
    rounded: "{rounded.control}"
    padding: "12px 18px"
    height: "72px"
  search-field:
    backgroundColor: "{colors.receipt-paper}"
    textColor: "{colors.black-ink}"
    rounded: "{rounded.field}"
    padding: "10px 14px"
    height: "54px"
  status-tag:
    backgroundColor: "{colors.receipt-paper}"
    textColor: "{colors.cobalt-deep}"
    rounded: "{rounded.field}"
    padding: "2px 7px"
---

# Design System: 库存比价台

## Overview

**Creative North Star: "收银台的证据票据"**

界面把实时库存当成一张正在打印的价格凭证：冷白纸面承载密集而可核对的数据，黑墨建立秩序，钴蓝只标记同步与可执行动作，安全黄只落在当前最低价。它触感明确但不模拟一张不可操作的图片；标题、价格、状态和控件始终是可选择、可缩放、可读屏的真实内容。

系统面向低操作频率场景。打开页面后，状态、最低价、同款比价和完整库存按证据强度依次出现；大控制、18px 正文和移动端纵向票据重排优先于装饰完整性。

**Key Characteristics:**

- 一张实体票据，而不是后台卡片墙。
- 最低价先出现，完整依据紧随其后。
- 黑墨、钴蓝、安全黄各司一职。
- 纸纤维、油墨磨损和孔位只增加触感，不降低可读性。

## Colors

调色采用受限的“纸、墨、章、价签”四角色策略；状态色仅用于需要解释恢复路径的反馈。

### Primary

- **钴蓝同步章**：用于主动作、同步章、焦点与价格强调；深钴蓝承担悬停和正文上的高对比变体。

### Secondary

- **安全黄价签**：只标记每组最低价与最高优先级低价入口；柔黄用于整行提示，避免大面积高饱和。

### Neutral

- **冷白票据**：所有主内容的纸面。
- **冷灰台面**：票据之外的环境，只在桌面宽度可见。
- **黑色印墨**：标题、正文和结构线。
- **次级墨灰**：说明、时间和来源信息。
- **柔和账线**：行级虚线与非关键分隔。

### Named Rules

**The One Yellow Price Rule.** 安全黄只属于当前最低价；普通优惠、标签或装饰不得借用它。

**The Blue Means Action or State Rule.** 钴蓝只表示动作、焦点、同步状态或可点击价格，不能散落成无意义装饰。

## Typography

**Display Font:** Segoe UI Variable / Microsoft YaHei UI / PingFang SC（系统字体，避免阻塞大字体下载）
**Body Font:** Segoe UI Variable / Microsoft YaHei UI / PingFang SC  
**Data Font:** Bahnschrift（中文回退到正文栈）

**Character:** 标题是压实的热敏打印黑字，并通过透明油墨缺口遮罩获得真实磨损；正文保持工作型中文无衬线的稳定字形。价格使用表格数字，纵向扫读不会跳位。

### Hierarchy

- **Display**（700，桌面 4.8rem / 移动端 3rem，0.98）：页面唯一主标题。
- **Section Headline**（700–900，2rem，1.15）：今日低价、同款比价和分类库存。
- **Group Title**（700–850，1.35rem，1.3）：商品分类和同款标题。
- **Body**（400，18px，1.55）：主要说明、商品名与控件文案。
- **Label**（700–800，0.72–0.9rem）：来源、标签、表头和状态补充。
- **Price**（800–900，1.2rem 至 3.1rem，表格数字）：列表价格与低价登记条。

### Named Rules

**The Live Type Rule.** 核心文字永远保留为 DOM 文本；材质只能通过字体、遮罩和背景增强，不把标题、状态或价格栅格化。

## Layout

桌面以一张最大 1480px 的票据为唯一主表面，外边距 16px，内部横向 42px、纵向 24px。桌面首屏顺序为标题/同步状态、三枚收银按键、搜索与同步摘要、今日低价、同款或分类清单起点；760px 以下将今日低价提前到控制区之前，保证首屏出现真实价格。

低价登记条在宽屏使用四列；1050px 以下改为两列，移动端仍保持两列紧凑价签。商品行在桌面使用商品、店铺、说明、库存、价格五列，其中商品列获得最多宽度，库存与价格右对齐。760px 以下隐藏表头并将每项重排为双列票据条：商品和标签跨满宽度，店铺在左，价格与库存在右，不产生横向滚动；超过 6 件的分类提供 48px 高展开按钮。

纵向节奏使用 14px 控件间距、24px 主要内边距与 30px 区段间隔。虚线分联和实线组头共同承担信息层级。

## Elevation & Depth

系统几乎完全扁平。唯一的结构阴影属于整张桌面票据（`0 20px 55px rgba(20, 29, 40, 0.16)`），表示纸张位于冷灰台面之上；内部控件、低价条和清单用边框、墨色和纸面层次，不叠加卡片阴影。移动端票据贴满视口，移除外部阴影。

**The One Sheet Rule.** 页面只有一张被抬起的纸；内部不得出现带独立阴影的浮动卡片。

## Shapes

形状接近收银设备与裁切票据：控件圆角 4px，输入框 3px，标签使用方正 1px 描边。区段以实线、双线或虚线分隔；两侧重复圆孔建立连续纸卷轮廓。同步章允许约一度旋转和不均匀双框，其他元素保持严格对齐。

## Components

### Register Controls

- **Shape:** 方正控制键（4px），最小高度 72px；实际桌面渲染约 82px。
- **Primary:** 钴蓝底、冷白字，刷新图标与文字同一行。
- **Secondary:** 冷白底、黑墨或深钴蓝字；选中态以钴蓝描边表达。
- **Hover / Focus:** 主按钮转深钴蓝，次按钮转冷灰；键盘焦点统一 4px 钴蓝实线并外移 3px。
- **Icon language:** 漏斗、刷新、时钟均使用 32px 方形视窗、2.35px 方端线条。

### Search Field

- **Style:** 2px 黑墨描边、3px 小圆角、54px 高；清空按钮与输入框共享外轮廓。
- **Focus:** 使用全局 4px 焦点环，不依赖仅有颜色的边框变化。
- **Copy:** 占位文案明确提示可使用语音输入。

### Lowest-Price Register

- **Structure:** 四个类别赢家共享一个外框，虚线列分隔；第一项使用安全黄整面，其他项保持票据纸。
- **Data:** 类别、排名、价格、店铺和库存均为真实文本；价格使用表格数字。
- **Responsive:** 1050px 以下两列，移动端压缩字号和间距以保持首屏价格可见。

### Ledger Rows

- **Structure:** 五列证据行，组头使用冷灰纸面和实线；普通行以柔和虚线收口。
- **Cheapest state:** 柔黄横向价签从商品列向内收束，并附“最便宜”标签。
- **Unavailable state:** 冷灰纸面和次级墨色，但仍允许打开详情核对。
- **Mobile:** 重排而非横向滚动；价格与库存始终留在右侧视觉轴。

### Status Stamp and Tags

- **Stamp:** 项目内旧化钴蓝双框 SVG 承担材质，内部状态仍为实时文本。
- **Tags:** 1px 深钴蓝描边、2px × 7px 内边距、0.72rem 粗体；同款店数、接码状态和质保信息共享同一语法。

## Do's and Don'ts

### Do:

- **Do** 让有货、最低价、店铺和库存数量在数秒内可扫到。
- **Do** 保持正文至少 18px、交互目标至少 48px、焦点环 4px。
- **Do** 用虚线、实线、墨色和留白建立层级，让同类价格保持右对齐。
- **Do** 让所有远端商品文案以 `textContent` 进入页面，保留信任边界。
- **Do** 为动态状态提供可读屏文字；图标只作辅助。

### Don't:

- **Don't** 把页面改成圆角卡片墙、统计图或营销首屏。
- **Don't** 用安全黄强调非最低价内容，或用钴蓝制造无意义装饰。
- **Don't** 把核心文字做进图片，或以纸张纹理降低对比度。
- **Don't** 在移动端保留需要横向拖动的桌面表格。
- **Don't** 为内部区块增加独立阴影；整张票据是唯一被抬起的表面。

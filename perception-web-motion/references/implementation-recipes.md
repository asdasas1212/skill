# 实现配方

这些配方是对原站机制的通用化，包含工程补强。参数是起点，不是所有页面的强制规格。

## 1. 视觉分层与动效预算

推荐背景层顺序：纯色底 → CSS 柔光 → Canvas 几何 → 遮罩提高文字对比 → 内容。
为背景建立明确 stacking context，装饰层 `pointer-events: none`；
不要用含义不明的负 z-index 让 Canvas 落到 body 后面。

| 层 | 方法 | 参考起点 | 为什么 |
| --- | --- | --- | --- |
| 柔光 | radial-gradient + blur + transform | 16–20s | 大范围、低频变化留给 CSS |
| 标题 | background-clip + background-position | 8–12s | 无需逐字更新 DOM |
| 进入视口 | observer + opacity/translate | 0.6–0.8s，40–70ms 错峰 | 一次进入即可，正文易于阅读 |
| 按钮 / 卡片 | transform、边框、局部 radial-gradient | 0.15–0.3s | 清晰响应输入 |
| 框 / 点 | 有生命周期的数据 + Canvas RAF | 每 0.5–0.8s 生成，低于十几个对象 | 控制密度与绘制成本 |
| token / 图形 | 单一可取消事件序列 | 20–80ms / 事件，结束停留 | 时间进度表达因果 |

不要给所有卡片叠加 blur、持续呼吸、倾斜、弹跳和描边流光。
背景应避开标题与主按钮，窄屏减少装饰。

## 2. Canvas 的坐标与生命周期

每次 resize 从布局读取宽高，像素缓冲区乘以受限 DPR，之后重新 `setTransform`。
不要每次 `scale` 累积，也不要在每个动画帧读取所有 DOM 尺寸。

```js
function sizeCanvas(canvas, context) {
  const { width, height } = canvas.getBoundingClientRect();
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { width, height };
}
```

点阵的邻域权重可用 `max(0, 1 - distance / radius)`，
再把权重映射到半径和透明度；无需完整物理粒子系统。

检测框对象至少含位置、尺寸、颜色、标签、出生时间和寿命。
按 elapsed time 算入场与淡出，按过期时间回收；控制对象上限，
避免向中央标题范围生成；缩小视口时重新约束几何。

一个组件只持有一个 RAF id。可见性、动效许可、页面隐藏和卸载共同决定是否调度下一帧。
恢复时不要重放一大段后台积累的生成事件；用新的时间基点。

## 3. 同步演示与取消

业务数据和演示机制分开。最小数据模型：

```js
{
  id: "locate",
  label: "Locate",
  prompt: "Find the marked object.",
  response: "<ref>object</ref><box><120><210><640><860></box>",
  sourceKind: "illustration"
}
```

真实结果回放可以增加来源、输入图和预计算 mask 路径。不要默认请求外部模型服务。
已有流式模型接口时，让同一个 renderer 消费真实事件；不要维护两套不一致的视觉逻辑。

```js
let revision = 0;
async function replay(sample) {
  const mine = ++revision;
  const stillCurrent = () => mine === revision;
  resetPresentation();
  await loadInput(sample);
  if (!stillCurrent()) return;
  for (const event of makeEvents(sample)) {
    await waitForNextEvent();
    if (!stillCurrent()) return;
    applyEventToTextAndGeometry(event);
  }
  if (stillCurrent()) showComplete();
}
function cancelReplay() { revision += 1; }
```

上面是机制示意，函数应按项目实现。生产页面也要处理加载错误和可取消定时器。
更复杂接口可用 `AbortController` 取消请求，同时保留 revision 防止无法取消的等待回写。
“pause” 应有明确语义：停止在当前状态，或立即展示完成态。模板采用后者，并在按钮命名中表达。

数值 token 只在 box / point 模式下累积，数量必须匹配；
校验有限值、0–1000 范围、盒子的左右和上下顺序。错误 token 保留为文本，不画错误几何。
对来自数据的内容用 `textContent`；不能把模型原始输出拼到 `innerHTML`。

## 4. 图像与覆盖层对齐

当 stage 宽高比与图一致时，归一化坐标可以直接换算：

`left = x0 / 10%`，`top = y0 / 10%`，
`width = (x1 - x0) / 10%`，`height = (y1 - y0) / 10%`。

如果使用 `object-fit: contain`，需把覆盖层放在**实际图像内容矩形**上，
而不是包含留白的外壳。若使用 `cover`，则必须应用相同裁切变换；
不要一边裁图一边仍按未裁切整图坐标绘制。

内联 SVG 可直接共享 `viewBox="0 0 1000 1000"`，把图片、框、点、mask 放进同一坐标系。
标签可能越界时改变标签朝向 / 使用 HTML 辅助图例；不要只靠隐藏溢出裁掉信息。

`<OBJ>` 事件应绑定到已知 mask/cutout，而不是随意生成一个看似精确的轮廓。
简化的示意蒙版必须明确标为示意。

## 5. 按需增加附属模块

- **结果 explorer**：数据中明确 `higher/lower is better`；按正确方向排序；
  条宽可按当前最大值归一化，但标签仍显示原始单位，不能让读者误以为条长就是百分比。
  使用真实数据或清晰标明示例，不填“好看”的假结果。
- **对比滑杆**：两层同尺寸媒体、`clip-path`、指针捕获；
  同时提供键盘可操作的 range 控件、标签与当前值。
- **图像放大**：优先用原生 dialog；支持 Escape、关闭按钮、描述、焦点进入和恢复。
- **代码复制**：保留可选择文本，在安全上下文中使用 Clipboard API；
  失败时显示明确回退，不静默宣称复制成功。

## 6. 交互验证场景

1. 启动长任务，立刻切换两次，再重播。终端和覆盖层只属于最终任务。
2. 在输入素材加载中切任务。旧 decode 不改变新布局或写入错误状态。
3. 演示进入视口自动开始，手动选择后等待原定轮播时间，选中任务仍保持。
4. 切到后台或离开首屏，再返回；没有成倍 RAF、几何爆发或跳过整段的后台回放。
5. 关闭动效，再更改系统 reduced-motion；CSS、Canvas、终端和自动轮播都遵守选择。
6. 检查手机、键盘、无 JS 可读性，以及素材加载失败的错误状态。

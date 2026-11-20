/* Replace the brand, copy and task data here. All samples below are illustrative. */
window.PERCEPTION_CONTENT = {
  brand: "Signal Atlas",
  title: "From signals",
  titleAccent: "to structure.",
  intro: "让每一步理解都有迹可循。把文本、坐标与像素放在同一个时间轴上，让复杂能力变得直观。",
  commands: ["observe → locate → reveal", "coordinates become geometry", "make the process visible"],
  tasks: [
    {
      id: "detect", label: "检测 / Detect", name: "Object detection",
      prompt: "Locate the plant and the cup.",
      response: "<ref>plant</ref><box><160><180><440><790></box>\n<ref>cup</ref><box><610><410><890><815></box>",
      summary: "完成：检测框已标出绿植和杯子。",
      sourceKind: "illustration"
    },
    {
      id: "point", label: "指点 / Point", name: "Visual pointing",
      prompt: "Point to the center of the cup.",
      response: "<ref>cup center</ref><point><710><610></point>",
      summary: "完成：点已标在杯子中心。",
      sourceKind: "illustration"
    },
    {
      id: "segment", label: "蒙版 / Segment", name: "Prepared mask reveal",
      prompt: "Reveal the prepared mask of the cup body.",
      response: "<ref>cup body</ref><box><625><415><795><790></box><OBJ>",
      summary: "完成：已显露预先绘制的杯身示意蒙版。",
      maskId: "mask-layer",
      sourceKind: "illustration"
    }
  ]
};

import { useEffect, useRef, useState } from "react";

/** 按住左键横向平移一个可滚动容器，同时把"拖动"和"点击"分开。

 * 按下的一瞬间无法判断用户想拖动还是想点击，只能等他动一下：位移超过
 * 阈值就算拖动。拖动结束的那次 click 会被在捕获阶段吞掉，否则从卡片
 * 上开始拖会顺带把卡片展开。
 *
 * 落点在输入框、按钮这类可交互元素上时不启动拖动，否则输入框里选一段
 * 文字就会把整条时间线拖走。
 */

const DRAG_THRESHOLD = 3;

const INTERACTIVE = "input, textarea, select, button, a, [data-no-drag]";

export function useDragPan<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [dragging, setDragging] = useState(false);
  const state = useRef({
    down: false,
    moved: false,
    startX: 0,
    startScroll: 0,
  });

  useEffect(() => {
    const node = ref.current;
    if (!node) {
      return;
    }

    function onMouseDown(event: MouseEvent) {
      if (event.button !== 0) {
        return;
      }
      const target = event.target as HTMLElement | null;
      if (target?.closest(INTERACTIVE)) {
        return;
      }
      state.current = {
        down: true,
        moved: false,
        startX: event.clientX,
        startScroll: node!.scrollLeft,
      };
      setDragging(true);
      event.preventDefault();
    }

    function onMouseMove(event: MouseEvent) {
      if (!state.current.down) {
        return;
      }
      const dx = event.clientX - state.current.startX;
      if (Math.abs(dx) > DRAG_THRESHOLD) {
        state.current.moved = true;
      }
      node!.scrollLeft = state.current.startScroll - dx;
    }

    function onMouseUp() {
      if (!state.current.down) {
        return;
      }
      state.current.down = false;
      setDragging(false);
    }

    function onClickCapture(event: MouseEvent) {
      if (!state.current.moved) {
        return;
      }
      state.current.moved = false;
      event.stopPropagation();
      event.preventDefault();
    }

    node.addEventListener("mousedown", onMouseDown);
    node.addEventListener("click", onClickCapture, true);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    // 鼠标在窗口外松开时 mouseup 收不到，标记会一直停在"正在拖"。
    window.addEventListener("mouseleave", onMouseUp);

    return () => {
      node.removeEventListener("mousedown", onMouseDown);
      node.removeEventListener("click", onClickCapture, true);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      window.removeEventListener("mouseleave", onMouseUp);
    };
  }, []);

  return { ref, dragging };
}

// 弹框遮罩点击关闭：mousedown 与 mouseup 都发生在遮罩上才触发 onClose。
// 解决：在弹框内文本框按住左键拖动选择文字、松开时鼠标落到遮罩上，
// 浏览器把 click 派发到遮罩（按下/松开点的共同祖先）导致 @click.self 误关弹框。
export function useMaskClose(onClose) {
  let downOnOverlay = false
  return {
    onMaskMouseDown(e) {
      downOnOverlay = e.target === e.currentTarget
    },
    onMaskMouseUp(e) {
      if (downOnOverlay && e.target === e.currentTarget) onClose()
      downOnOverlay = false
    }
  }
}

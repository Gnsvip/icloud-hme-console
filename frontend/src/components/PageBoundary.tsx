import { Component, type ReactNode } from "react";
import { Button } from "./common";

export class PageBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return (
      <div role="alert" className="panel">
        <p>页面加载失败，请刷新后重试。</p>
        <Button onClick={() => location.reload()}>刷新页面</Button>
      </div>
    );
    return this.props.children;
  }
}

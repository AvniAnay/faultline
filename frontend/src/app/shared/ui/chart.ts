import { Component, ElementRef, OnDestroy, effect, input, viewChild } from '@angular/core';
import { BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer]);

@Component({
  selector: 'ui-chart',
  host: { class: 'block' },
  template: `<div #host class="h-64 w-full" role="img" [attr.aria-label]="label()"></div>`,
})
export class UiChart implements OnDestroy {
  readonly option = input.required<echarts.EChartsCoreOption>();
  readonly label = input('Chart');
  private readonly host = viewChild.required<ElementRef<HTMLDivElement>>('host');
  private chart?: echarts.ECharts;
  private observer?: ResizeObserver;

  constructor() {
    effect(() => {
      const el = this.host().nativeElement;
      if (!this.chart) {
        this.chart = echarts.init(el);
        this.observer = new ResizeObserver(() => this.chart?.resize());
        this.observer.observe(el);
      }
      this.chart.setOption(this.option(), true);
    });
  }

  ngOnDestroy() {
    this.observer?.disconnect();
    this.chart?.dispose();
  }
}

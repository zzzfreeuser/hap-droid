/*
 * Copyright (c) 2024 Huawei Device Co., Ltd.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import fs from 'fs';
import { Device } from '../device/device';
import { Event } from '../event/event';
import { Hap } from '../model/hap';
import { Page } from '../model/page';
import { Policy, PolicyName } from './policy';
import { ExitEvent } from '../event/system_event';
import path from 'path';
import { EventBuilder } from '../event/event_builder';
import { PTG } from '../model/ptg';

export class ReplayPolicy extends Policy {
    steps: [Page, Event][];
    currentStep: number;

    // 新增：PTG相关状态
    private ptg: PTG;
    private lastEvent?: Event;
    private lastPage?: Page;
    private currentPage?: Page;

    constructor(device: Device, hap: Hap, name: PolicyName, reportRoot: string) {
        super(device, hap, name);
        this.steps = [];
        this.currentStep = 0;

        // replay 场景下通常不需要 randomInput
        this.ptg = new PTG(hap, false);

        this.loadEvents(path.join(reportRoot, 'events'));
    }

    async generateEvent(page: Page): Promise<Event> {
        // 当前真实页面（回放执行后采集到的页面）
        this.currentPage = page;

        // 用“上一个事件 + 上一个页面 + 当前页面”更新 PTG
        this.updatePtg();

        // 步骤跑完：导出最终图并退出
        if (this.currentStep === this.steps.length) {
            // this.ptg.addTransitionToStop(page);
            // this.ptg.dumpSvg(this.device.getOutput(), 'http://localhost:3001');
            this.stop();
            return new ExitEvent();
        }

        this.logger.info(page.getContentSig(), this.steps[this.currentStep][0].getContentSig());

        const event = this.steps[this.currentStep++][1];

        // 为下一轮 updatePtg 准备“上一条边”的起点和事件
        this.lastPage = this.currentPage;
        this.lastEvent = event;

        return event;
    }

    private updatePtg(): void {
        if (this.lastEvent && this.lastPage && this.currentPage) {
            this.ptg.addTransition(this.lastEvent, this.lastPage, this.currentPage);
            this.ptg.addTransitionToStop(this.currentPage);
            this.ptg.dumpSvg(this.device.getOutput(), 'http://localhost:3001');
        }
    }

    private loadEvents(reportRoot: string) {
        if (!fs.existsSync(reportRoot)) {
            this.logger.error(`Path ${reportRoot} is not exists.`);
            process.exit();
        }

        // 建议排序，保证回放顺序稳定
        const files = fs.readdirSync(reportRoot)
            .filter((f) => f.endsWith('.json'))
            .sort();

        for (const file of files) {
            const report = JSON.parse(fs.readFileSync(path.resolve(reportRoot, file), { encoding: 'utf-8' }));
            const event = EventBuilder.createEventFromJson(report.event);
            const page = Page.fromJson(report.from);
            this.steps.push([page, event]);
        }
    }
}

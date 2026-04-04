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

import OpenAI from 'openai';
// import { Component } from '../model/component';
import { SerializeUtils } from '../utils/serialize_utils'

export class ReplayPolicy extends Policy {
    steps: [Page, Event][];
    currentStep: number;

    // 新增：PTG相关状态
    private ptg: PTG;
    private lastEvent?: Event;
    private lastPage?: Page;
    private currentPage?: Page;

    private openai: OpenAI;
    private reports: any[] = [];

    private static GPT_CONFIG: { baseURL: string; apiKey: string };

    constructor(device: Device, hap: Hap, name: PolicyName, reportRoot: string) {
        super(device, hap, name);
        this.steps = [];
        this.currentStep = 0;

        // replay 场景下通常不需要 randomInput
        this.ptg = new PTG(hap, false);

        this.loadEvents(path.join(reportRoot, 'events'));
        
        ReplayPolicy.GPT_CONFIG = this.loadConfig();
        this.openai = new OpenAI(ReplayPolicy.GPT_CONFIG);
    }

    private loadConfig(): { baseURL: string; apiKey: string } {
        const configPath = path.resolve(__dirname, '../../config.json'); // 配置文件路径
        try {
            const configData = fs.readFileSync(configPath, 'utf-8');
            const config = JSON.parse(configData);
            return config.GPT_CONFIG;
        } catch (error) {
            this.logger.error(`加载配置文件失败: ${error}`);
            throw new Error("无法加载 GPT 配置，请检查配置文件是否存在且格式正确。");
         }
    }

    private async tryRelocateEventComponentByLLM(
        event: Event,
        sourceEventJson: any,
        AndroidPage: Page,
        currentPage: Page
    ): Promise<Event> {
        try {
            // 仅处理带 component 的 UI 事件
            const et = sourceEventJson?.type;
            if (!sourceEventJson || !sourceEventJson.component) return event;
            if (!['TouchEvent', 'LongTouchEvent', 'InputTextEvent', 'ScrollEvent'].includes(et)) return event;

            const candidates = currentPage.getComponents().filter(c => c.hasUIEvent && c.hasUIEvent());
            if (!candidates.length) return event;

            const candidatePayload: string[] = candidates.map((c: any) => SerializeUtils.serialize(c));

            const srcComp = JSON.stringify(sourceEventJson.component);
            const AndroidPageJson = JSON.stringify(AndroidPage);
            const currentPageJson = JSON.stringify(SerializeUtils.serialize(currentPage));

            const prompt = [
                '你是移动端UI组件匹配助手。任务是任根据安卓事件中的组件信息, 在鸿蒙候选组件列表中选最匹配的一个.',
                '由于安卓和鸿蒙ui组件可能存在差异,以及安卓设备和鸿蒙设备屏幕尺寸不同,所以同一组件坐标可能不同,相同坐标也可能不对应同一组件',
                '你应当直接从鸿蒙候选组件列表中返回一个组件的json, 不要返回任何额外信息以及修改信息,特别是坐标信息,一定要保留鸿蒙组件原有坐标.',
                `为了便于更好的判断,再给出当前安卓组件属的安卓组件树和鸿蒙候选组件所在的鸿蒙页面的组件树的结构信息,但请注意,这些结构信息可能不完整或者有误,你需要学会根据这些不完全的信息进行判断.如果无法判断出一个明确的组件,请返回鸿蒙候选组件列表中最相似的一个组件.`,
                `源组件: ${srcComp}`,
                `鸿蒙候选组件列表: ${JSON.stringify(candidatePayload)}`,
                `源安卓组件树: ${AndroidPageJson}`,
                `目标鸿蒙组件树: ${currentPageJson}`,
            ].join('\n');

            const completion = await this.openai.chat.completions.create({
                model: "Qwen/Qwen3.5-35B-A3B",
                messages: [{ role: 'user', content: prompt }]
            });

            const raw = completion.choices?.[0]?.message?.content?.trim() || '';
            const m = raw.match(/\{[\s\S]*\}/);
            if (!m) return event;

            const parsed = JSON.parse(m[0]);

            // 直接覆写事件组件（最小侵入）
            (event as any).component = parsed;

            let x = (parsed.bounds[0]['x'] + parsed.bounds[1]['x']) / 2;
            let y = (parsed.bounds[0]['y'] + parsed.bounds[1]['y']) / 2;
            (event as any).point = { 'x': x, 'y': y };

            // 如果事件有 point，改成目标组件中心点
            // if ((event as any).point !== undefined) {
            //     const center = target.getCenterPoint ? target.getCenterPoint() : null;
            //     if (center) (event as any).point = center;
            // }

            return event;
        } catch (e) {
            this.logger.warn(`LLM component match failed: ${e}`);
            return event;
        }
    }

    async generateEvent(page: Page): Promise<Event> {
        // 当前真实页面（回放执行后采集到的页面）
        this.currentPage = page;

        // 用“上一个事件 + 上一个页面 + 当前页面”更新 PTG
        this.updatePtg();

        // 步骤跑完：导出最终图并退出
        if (this. currentStep === this.steps.length) {
            // this.ptg.addTransitionToStop(page);
            // this.ptg.dumpSvg(this.device.getOutput(), 'http://localhost:3001');
            this.stop();
            return new ExitEvent();
        }

        if (this.currentStep == 0) {
            this.currentStep++;
            return this.steps[0][1];
        }

        this.logger.info(page.getContentSig(), this.steps[this.currentStep][0].getContentSig());

        const stepIdx = this.currentStep;
        let event = this.steps[this.currentStep][1];

        const report = this.reports[stepIdx];
        event = await this.tryRelocateEventComponentByLLM(event, report?.event, 
            this.steps[this.currentStep][0], 
            page);

        this.currentStep++;

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
            this.reports.push(report); // 新增
        }
    }
}

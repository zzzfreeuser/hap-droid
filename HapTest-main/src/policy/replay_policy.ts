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
import { SerializeUtils } from '../utils/serialize_utils';
import sharp from 'sharp';

function imageToDataUrl(imagePath: string): string {
    if (!fs.existsSync(imagePath) || !fs.statSync(imagePath).isFile()) {
        throw new Error("Image file not found: " + imagePath);
    }

    var picType = '';
    if (imagePath.endsWith('.png')) {
        // PNG 图片
        picType = 'png';
    } else if (imagePath.endsWith('.jpg') || imagePath.endsWith('.jpeg')) {
        // JPEG 图片
        picType = 'jpg';
    }

    const imageData = fs.readFileSync(imagePath);
    const base64Encoded = imageData.toString("base64");

    return "data:image/" + picType + ";base64," + base64Encoded;
}

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
    // private endTime: number = 0;

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

            const AndroidPageSnapshot = AndroidPage.getSnapshot()?.screenCapPath;
            // const AndroidDeviceWidth = AndroidPage.getSnapshot()?.screenWidth;
            // const AndroidDeviceHeight = AndroidPage.getSnapshot()?.screenHeight;
            const harmonyPageSnapshot = currentPage.getSnapshot()!.screenCapPath;
            const androidImagePath = path.join(path.dirname(harmonyPageSnapshot || ''), 'temp_android_src.jpg');
            const harmonyImagePath = path.join(path.dirname(harmonyPageSnapshot || ''), 'temp_harmony_src.jpg');
            const harmonyViewPath = path.join(path.dirname(path.dirname(harmonyPageSnapshot || '')), 'views');
            if (!fs.existsSync(harmonyViewPath)) {
                fs.mkdirSync(harmonyViewPath, { recursive: true });
            }
            if (AndroidPageSnapshot != '') {
                await sharp(AndroidPageSnapshot).extract({
                    left: sourceEventJson['component']['bounds'][0]['x'], 
                    top: sourceEventJson['component']['bounds'][0]['y'],  
                    width: sourceEventJson['component']['bounds'][1]['x'] - sourceEventJson['component']['bounds'][0]['x'],
                    height: sourceEventJson['component']['bounds'][1]['y'] - sourceEventJson['component']['bounds'][0]['y'],
                }).toFile(androidImagePath);
            }

            // const prompt = [
            //     '你是移动端UI组件匹配助手。任务是任根据安卓事件中的组件信息, 在鸿蒙候选组件列表中选最匹配的一个.',
            //     '由于安卓和鸿蒙ui组件可能存在差异,以及安卓设备和鸿蒙设备屏幕尺寸不同,所以同一组件坐标可能不同,相同坐标也可能不对应同一组件',
            //     '你要把安卓组件的json和截图和鸿蒙组件的json和截图做对比,给相似度打分(0-100分)',
            // ].join('\n');

            // await this.openai.chat.completions.create({
            //     model: "glm-5.1",
            //     messages: [{ role: 'user', content: prompt }]
            // }); 

            // let candidateScores: [Component, number][] = [];

            // for (const candidate of candidates) {
            //     const bounds = candidate?.bounds;
            //     if (!Array.isArray(bounds) || bounds.length < 2) {
            //         continue;
            //     }
            //     await sharp(harmonyPageSnapshot!).extract({
            //         left: bounds[0]['x'], 
            //         top: bounds[0]['y'], 
            //         width: candidate.getWidth(),
            //         height: candidate.getHeight(),
            //     }).toFile(harmonyImagePath); 

            //     const message = [
            //         `当前安卓组件: ${srcComp}, 候选鸿蒙组件: ${SerializeUtils.serialize(candidate)}`,
            //         `为了更好地判断,再给出当前安卓组件所在的安卓页面:${AndroidPageJson}`,
            //         `和候选鸿蒙组件所在页面: ${currentPageJson}`,
            //         `以及两者总页面的截图`,
            //         `根据这些信息和截图,给两者相似度打分(0-100分, 越高表示越相似),直接给出分数，不要任何额外信息`,
            //     ].join('\n');

            //     const completion = await this.openai.chat.completions.create({
            //         model: "glm-4.6v",
            //         messages: [
            //             {
            //                 "role": "user",
            //                 "content": [
            //                     {
            //                         "type": "text",
            //                         "text": message,
            //                     },
            //                     {
            //                         "type": "image_url",
            //                         "image_url": {
            //                             "url": imageToDataUrl(androidImagePath),
            //                         },
            //                     },
            //                     {
            //                         "type": "image_url",
            //                         "image_url": {
            //                             "url": imageToDataUrl(harmonyPageSnapshot),
            //                         },
            //                     },
            //                 ],
            //             }
            //         ],
            //     });
            //     const raw = completion.choices?.[0]?.message?.content?.trim() || '';
            //     const scoreMatch = raw.match(/(\d{1,3})/);
            //     const score = scoreMatch ? parseInt(scoreMatch[1]) : 0;
            //     candidateScores.push([candidate, score]);
            // }
            // candidateScores.sort((a, b) => b[1] - a[1]);

            const prompt = [
                '你是移动端UI组件匹配助手。任务是任根据安卓事件中的组件信息, 在鸿蒙候选组件列表中选最匹配的一个.',
                '由于安卓和鸿蒙ui组件可能存在差异,以及安卓设备和鸿蒙设备屏幕尺寸不同,所以同一组件坐标可能不同,相同坐标也可能不对应同一组件',
                '你应当直接从鸿蒙候选组件列表中返回一个组件的json, 不要返回任何额外信息以及修改信息,特别是坐标信息,一定要保留鸿蒙组件原有坐标.',
                `为了便于更好的判断,再给出当前安卓组件所在的安卓组件树和鸿蒙候选组件所在的鸿蒙页面的组件树的结构信息,但请注意,这些结构信息可能不完整或者有误,你需要学会根据这些不完全的信息进行判断.如果无法判断出一个明确的组件,请返回鸿蒙候选组件列表中最相似的一个组件.`,
                `源组件: ${srcComp}`,
                `鸿蒙候选组件列表: ${JSON.stringify(candidatePayload)}`,
                `源安卓组件树: ${AndroidPageJson}`,
                `目标鸿蒙组件树: ${currentPageJson}`,
                `此外,再给出安卓组件和鸿蒙页面的截图,你应当根据候选组件的坐标对应图上的区域与安卓组件截图做对比,判断出最匹配的鸿蒙组件`,
            ].join('\n');

            // const completion = await this.openai.chat.completions.create({
            //     model: "glm-5.1",
            //     messages: [{ role: 'user', content: prompt }]
            // });

            // const cvPrompt = [
            //     `现在给出安卓组件截图和鸿蒙页面截图,直接返回鸿蒙页面中和安卓组件最相似的组件的左上角的坐标和右下角的坐标,`,
            //     `为了更准的判断,现给出安卓设备的屏幕尺寸、安卓组件左上角坐标以及鸿蒙设备的屏幕尺寸`,
            //     `安卓设备尺寸: ${AndroidDeviceWidth}x${AndroidDeviceHeight}`,
            //     `安卓组件左上角坐标: (${sourceEventJson['component']['bounds'][0]['x']}, ${sourceEventJson['component']['bounds'][0]['y']})`,
            //     `鸿蒙设备尺寸: ${currentPage.getSnapshot()?.screenWidth}x${currentPage.getSnapshot()?.screenHeight}`,
            //     `注意如果当前鸿蒙页面有多个位置都和安卓组件类似,则需要根据坐标相对位置判断`,
            //     `返回格式为[{"x": number, "y": number}, {"x": number, "y": number}]不要任何额外信息`,
            // ].join('\n');

            const completion = await this.openai.chat.completions.create({
                model: "glm-4.6v",
                messages: [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt,
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": imageToDataUrl(androidImagePath),
                                },
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": imageToDataUrl(harmonyPageSnapshot),
                                },
                            },
                        ],
                    }
                ],
            });
            const raw = completion.choices?.[0]?.message?.content?.trim() || '';
            const m = raw.match(/\{[\s\S]*\}/);
            if (!m) return event;
            // const cvRaw = cvCompletion.choices?.[0]?.message?.content?.trim() || '';
            // const cvMatch = cvRaw.match(/\[[\s\S]*\]/);
            // const cvParsed = cvMatch ? JSON.parse(cvMatch[0]) : null;   

            const parsed = JSON.parse(m[0]);

            // 直接覆写事件组件（最小侵入）
            // if (!candidateScores.length) return event;

            // const parsed = candidateScores[0][0];
            (event as any).component = parsed;
            // (event as any).component['bounds'] = cvParsed; // 用 LLM 预测的坐标替换原组件坐标
            // (event as any).component['origBounds'] = cvParsed; // 先保留一份原始坐标，万一后续需要调整坐标再用
            const parsedBounds = parsed?.bounds;
            if (
                !Array.isArray(parsedBounds) ||
                parsedBounds.length < 2 ||
                parsedBounds[0]?.['x'] === undefined ||
                parsedBounds[0]?.['y'] === undefined ||
                parsedBounds[1]?.['x'] === undefined ||
                parsedBounds[1]?.['y'] === undefined
            ) {
                return event;
            }
 
            await sharp(harmonyPageSnapshot).extract({
                left: parsedBounds[0]['x'],
                top: parsedBounds[0]['y'],
                width: parsed.getWidth(),
                height: parsed.getHeight(),
            }).toFile(harmonyImagePath);

            await sharp(harmonyPageSnapshot).extract({
                left: parsedBounds[0]['x'],
                top: parsedBounds[0]['y'],
                width: parsed.getWidth(),
                height: parsed.getHeight(),
            }).toFile(path.join(harmonyViewPath, `view_${this.currentStep}.jpg`));

            let x = (parsedBounds[0]['x'] + parsedBounds[1]['x']) / 2;
            let y = (parsedBounds[0]['y'] + parsedBounds[1]['y']) / 2;
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
        if (this.currentStep === this.steps.length) {
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

    private async updatePtg(): Promise<void> {
        if (this.lastEvent && this.lastPage && this.currentPage) {
            this.ptg.addTransition(this.lastEvent, this.lastPage, this.currentPage);
            this.ptg.addTransitionToStop(this.currentPage);
            await this.ptg.dumpSvg(
                this.device.getOutput(), 
                path.join(this.device.getOutput(), `/views/view_${this.currentStep}.jpg`)
            );
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

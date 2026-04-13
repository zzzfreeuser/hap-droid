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
import { attribute as _, Digraph, Node, Edge, toDot } from 'ts-graphviz';
import { Event } from '../event/event';
import { Hap } from './hap';
import DirectedGraph from 'graphology';
import { bidirectional } from 'graphology-shortest-path';
import { RandomUtils } from '../utils/random_utils';
import { StopHapEvent } from '../event/system_event';
import { Page } from './page';
import { getLogger } from 'log4js';
import * as path from 'path';
const logger = getLogger();

type EdgeAttributeType = Map<string, { id: number; event: Event }>;

export interface Transition {
    from: Page;
    to: Page;
    event: Event;
}

/**
 * UI Page transition graph
 */
export class PTG {
    private hap: Hap;
    private randomInput: boolean;
    private transitions: Transition[];
    private pageContentGraph: DirectedGraph<Page, EdgeAttributeType>;
    private pageStructualGraph: DirectedGraph<Page[], EdgeAttributeType>;
    private ineffectiveEvent: Set<string>;
    private effectiveEvent: Set<string>;
    private exploredPage: Set<string>;
    private reachedPage: Set<string>;
    private exploredAbility: Set<string>; //xmq
    private firstPage?: Page;
    private stopEvent: StopHapEvent;
    private stopPage?: Page;
    private wantTransition?: Transition;
    private startTime: number = Date.now();

    constructor(hap: Hap, randomInput: boolean) {
        this.hap = hap;
        this.randomInput = randomInput;
        this.transitions = [];
        this.pageContentGraph = new DirectedGraph();
        this.pageStructualGraph = new DirectedGraph();
        this.ineffectiveEvent = new Set();
        this.effectiveEvent = new Set();
        this.exploredPage = new Set();
        this.exploredAbility = new Set();
        this.reachedPage = new Set();
        this.stopEvent = new StopHapEvent(this.hap.bundleName);
    }

    setWantTransition(transition: Transition) {
        this.wantTransition = transition;
        logger.info(`ptg want transition ${transition.from.getContentSig()} -> ${transition.to.getContentSig()}`);
    }

    addTransitionToStop(newPage: Page): void {
        if (!this.stopPage || !newPage.isForeground()) {
            return;
        }

        this.addTransition(this.stopEvent, newPage, this.stopPage);
    }

    addTransition(event: Event, oldPage: Page, newPage: Page): void {
        if (this.wantTransition) {
            logger.info(`ptg want transition ${oldPage.getContentSig()} -> ${newPage.getContentSig()}`);
            if (
                this.wantTransition.from === oldPage &&
                this.wantTransition.event === event &&
                this.wantTransition.to.getContentSig() !== newPage.getContentSig()
            ) {
                logger.info(
                    `ptg drop edge ${this.wantTransition.from.getContentSig()} -> ${this.wantTransition.to.getContentSig()}`
                );
                this.pageContentGraph.dropDirectedEdge(
                    this.wantTransition.from.getContentSig(),
                    this.wantTransition.to.getContentSig()
                );
                this.wantTransition = undefined;
            } else {
                logger.info(
                    `ptg not need drop ${this.wantTransition.from === oldPage}, ${this.wantTransition.event === event}, ${
                        this.wantTransition.to.getContentSig() !== newPage.getContentSig()
                    }`
                );
            }
        }

        this.addNode(oldPage);
        this.addNode(newPage);

        this.transitions.push({ from: oldPage, event: event, to: newPage });
        let eventPageSig = event.eventPageSig(oldPage);

        // ineffective event
        if (oldPage.getContentSig() === newPage.getContentSig()) {
            this.ineffectiveEvent.add(eventPageSig);
            return;
        }

        this.effectiveEvent.add(eventPageSig);

        if (!this.pageContentGraph.hasDirectedEdge(oldPage.getContentSig(), newPage.getContentSig())) {
            this.pageContentGraph.addDirectedEdge(oldPage.getContentSig(), newPage.getContentSig(), new Map());
            logger.info(`ptg add edge ${oldPage.getContentSig()} -> ${newPage.getContentSig()}`);
        }
        let attr = this.pageContentGraph.getEdgeAttributes(oldPage.getContentSig(), newPage.getContentSig());
        attr.set(eventPageSig, { event: event, id: this.effectiveEvent.size });

        if (!this.pageStructualGraph.hasDirectedEdge(oldPage.getStructualSig(), newPage.getStructualSig())) {
            this.pageStructualGraph.addDirectedEdge(oldPage.getStructualSig(), newPage.getStructualSig(), new Map());
        }

        attr = this.pageStructualGraph.getEdgeAttributes(oldPage.getStructualSig(), newPage.getStructualSig());
        attr.set(eventPageSig, { event: event, id: this.effectiveEvent.size });
    }

    removeTransition(event: Event, oldPage: Page, newPage: Page): void {
        // event bind oldState
        let eventStr = event.eventPageSig(oldPage);
        if (this.pageContentGraph.hasEdge(oldPage.getStructualSig(), newPage.getStructualSig())) {
            let attr = this.pageContentGraph.getEdgeAttributes(oldPage.getStructualSig(), newPage.getStructualSig);
            if (attr.has(eventStr)) {
                attr.delete(eventStr);
            }
            if (attr.size === 0) {
                this.pageContentGraph.dropEdge(oldPage.getStructualSig(), newPage.getStructualSig());
            }
        }

        if (this.pageStructualGraph.hasEdge(oldPage.getStructualSig(), newPage.getStructualSig())) {
            let attr = this.pageStructualGraph.getEdgeAttributes(oldPage.getStructualSig(), newPage.getStructualSig);
            if (attr.has(eventStr)) {
                attr.delete(eventStr);
            }
            if (attr.size === 0) {
                this.pageStructualGraph.dropEdge(oldPage.getStructualSig(), newPage.getStructualSig());
            }
        }
    }

    isEventExplored(event: Event, page: Page): boolean {
        let eventPageSig = event.eventPageSig(page);
        return this.effectiveEvent.has(eventPageSig) || this.ineffectiveEvent.has(eventPageSig);
    }

    isPageExplored(page: Page): boolean {
        if (this.exploredPage.has(page.getContentSig())) {
            return true;
        }

        for (const event of page.getPossibleUIEvents()) {
            if (!this.isEventExplored(event, page)) {
                return false;
            }
        }

        this.exploredPage.add(page.getContentSig());
        return true;
    }

    isAbilityExplored(abilityName: string): boolean {
        if (this.exploredAbility.has(abilityName)){
            return true;
        }
        this.exploredAbility.add(abilityName);
        return false;
    }

    isPageReached(page: Page): boolean {
        if (this.reachedPage.has(page.getContentSig())) {
            return true;
        }
        // todo
        this.reachedPage.add(page.getContentSig());
        return false;
    }

    getReachablePages(currentPage: Page): Page[] {
        let reachablePages: Page[] = [];
        if (!this.pageContentGraph.hasNode(currentPage.getContentSig())) {
            return reachablePages;
        }
        this.pageContentGraph.filterOutEdges(currentPage.getContentSig(), (edge, attr, source, target) => {
            let state = this.pageContentGraph.getNodeAttributes(target);
            reachablePages.push(state);
        });
        return reachablePages;
    }

    getNavigationSteps(from: Page, to: Page): [Page, Event][] | undefined {
        const path = bidirectional(this.pageContentGraph, from.getContentSig(), to.getContentSig());
        if (!path || path.length < 2) {
            logger.warn(`error get path from ${from.getContentSig()} to ${to.getContentSig()}`);
            return;
        }

        logger.info(`shortest path ${from.getContentSig()} -> ${to.getContentSig()} ${path}`);

        let steps: [Page, Event][] = [];
        let source = path[0];
        for (let i = 1; i < path.length; i++) {
            let sourceState = this.pageContentGraph.getNodeAttributes(source);
            let target = path[i];
            let edgeAttr = this.pageContentGraph.getEdgeAttributes(source, target);
            let eventKeys = Array.from(edgeAttr.keys());
            if (this.randomInput) {
                RandomUtils.shuffle(eventKeys);
            }
            let event = edgeAttr.get(eventKeys[0])?.event;
            steps.push([sourceState, event!]);
            source = target;
        }

        return steps;
    }

    async dumpSvg(output: string, rootUrl: string) {
        const dotGraph = new Digraph('PTG');
        dotGraph.node({
            fontname: 'Helvetica,Arial,sans-serif',
            fontsize: 12,
            width: 4,
            color: '#8383cc',
            fixedsize: true,
        });
        dotGraph.edge({ color: 'pink' });
        let nodes = new Map<string, Node>();
        for (const id of this.pageStructualGraph.nodes()) {
            let pages: Page[] = this.pageStructualGraph.getNodeAttributes(id);
            let faultLogs: Set<string> = new Set<string>();
            pages.map((v) =>
                v.getSnapshot()?.faultLogs.forEach((log) => {
                    let filename = path.basename(log);
                    if (!filename.includes('uitest')) {
                        faultLogs.add(filename);
                    }
                })
            );
            let dotNode = new Node(id, {
                [_.label]: `${id}\n${Array.from(faultLogs).join('\n')}`,
                // [_.URL]: `${rootUrl}/node/${id}`,
                [_.image]: `${pages[0].getSnapshot()?.screenCapPath}`,
            });
            dotGraph.addNode(dotNode);
            nodes.set(id, dotNode);
        }

        for (const source of this.pageStructualGraph.nodes()) {
            for (const target of this.pageStructualGraph.nodes()) {
                if (this.pageStructualGraph.hasDirectedEdge(source, target)) {
                    const edge = new Edge([nodes.get(source)!, nodes.get(target)!], {
                        [_.URL]: `${rootUrl}`,
                    });
                    dotGraph.addEdge(edge);
                }
            }
        }

        try {
            const dot = toDot(dotGraph);
            fs.writeFileSync(path.join(output, 'ptg.dot'), dot);
            // this.dumpHtml(output, dotGraph);
        } catch(error) {
            
        }

        return Date.now() - this.startTime;
    }

    /**
     * 生成网页可视化文件（ptg.html）
     * 依赖 d3-graphviz 在线脚本，打开 html 即可查看
     */
    dumpHtml(outputDir: string, dotGraph: Digraph): void {
        const dotPath = path.join(outputDir, 'ptg.dot');
        const htmlPath = path.join(outputDir, 'ptg.html');

        // 复用你现有 dot 导出逻辑（如果你当前方法名不同，替换成实际方法）
        // 例如：const dotContent = this.toDot();
        const dotContent = toDot(dotGraph);

        fs.writeFileSync(dotPath, dotContent, { encoding: 'utf-8' });

        const html = `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>HapTest PTG</title>
  <style>
    body { margin: 0; font-family: Arial, sans-serif; }
    #toolbar { padding: 10px; border-bottom: 1px solid #ddd; }
    #graph { width: 100vw; height: calc(100vh - 50px); overflow: auto; }
    textarea { width: 100%; height: 120px; font-family: Consolas, monospace; }
  </style>
  <script src="https://unpkg.com/d3@7"></script>
  <script src="https://unpkg.com/@hpcc-js/wasm@2.16.2/dist/index.min.js"></script>
  <script src="https://unpkg.com/d3-graphviz@5.1.0/build/d3-graphviz.min.js"></script>
</head>
<body>
  <div id="toolbar">
    <strong>HapTest PTG 可视化</strong>
  </div>
  <div id="graph"></div>
  <script>
    const dot = ${JSON.stringify(dotContent)};
    d3.select("#graph").graphviz().zoom(true).renderDot(dot);
  </script>
</body>
</html>`;

        fs.writeFileSync(htmlPath, html, { encoding: 'utf-8' });
    }

    private addNode(page: Page) {
        if (this.firstPage === undefined) {
            this.firstPage = page;
        }

        if (this.stopPage === undefined && page.isStop()) {
            this.stopPage = page;
        }

        if (!this.pageContentGraph.hasNode(page.getContentSig())) {
            this.pageContentGraph.addNode(page.getContentSig(), page);
            logger.info(`ptg add node ${page.getContentSig()}`);
        }

        if (!this.pageStructualGraph.hasNode(page.getStructualSig())) {
            this.pageStructualGraph.addNode(page.getStructualSig(), [page]);
        } else {
            this.pageStructualGraph.getNodeAttributes(page.getStructualSig()).push(page);
        }
        // reached ability
    }

    getExploredAbilities(): string[] {
        return Array.from(this.exploredAbility);
    }

    // output_ptg(output: string) {

    //     function list_to_html_table(dict_data: Map<string, string>[]): string {
    //         let table = "<table class=\"table\">\n"
    //         for (const [key, value] of dict_data) {
    //             table += "<tr><th>" + key + "</th><td>" + value + "</td></tr>\n";
    //         }
    //         table += "</table>"
    //         return table

    //     const utg_file_path = path.join(output, "utg.js");
    //     let utg_nodes = []
    //     let utg_edges = []
    //     for state_str in self.G.nodes():
    //         state = self.G.nodes[state_str]["state"]
    //         package_name = state.foreground_activity.split("/")[0]
    //         activity_name = state.foreground_activity.split("/")[1]
    //         short_activity_name = activity_name.split(".")[-1]

    //         state_desc = list_to_html_table([
    //             ("package", package_name),
    //             ("activity", activity_name),
    //             ("state_str", state.state_str),
    //             ("structure_str", state.structure_str)
    //         ])

    //         utg_node = {
    //             "id": state_str,
    //             "shape": "image",
    //             "image": os.path.relpath(state.screenshot_path, self.device.output_dir),
    //             "label": short_activity_name,
    //             # "group": state.foreground_activity,
    //             "package": package_name,
    //             "activity": activity_name,
    //             "state_str": state_str,
    //             "structure_str": state.structure_str,
    //             "title": state_desc,
    //             "content": "\n".join([package_name, activity_name, state.state_str, state.search_content])
    //         }

    //         if state.state_str == self.first_state_str:
    //             utg_node["label"] += "\n<FIRST>"
    //             utg_node["font"] = "14px Arial red"
    //         if state.state_str == self.last_state_str:
    //             utg_node["label"] += "\n<LAST>"
    //             utg_node["font"] = "14px Arial red"

    //         utg_nodes.append(utg_node)

    //     for state_transition in self.G.edges():
    //         from_state = state_transition[0]
    //         to_state = state_transition[1]

    //         events = self.G[from_state][to_state]["events"]
    //         event_short_descs = []
    //         event_list = []

    //         for event_str, event_info in sorted(iter(events.items()), key=lambda x: x[1]["id"]):
    //             event_short_descs.append((event_info["id"], event_str))
    //             if self.device.adapters[self.device.minicap]:
    //                 view_images = ["views/view_" + view["view_str"] + ".jpg"
    //                                for view in event_info["event"].get_views()]
    //             else:
    //                 view_images = ["views/view_" + view["view_str"] + ".png"
    //                                for view in event_info["event"].get_views()]
    //             event_list.append({
    //                 "event_str": event_str,
    //                 "event_id": event_info["id"],
    //                 "event_type": event_info["event"].event_type,
    //                 "view_images": view_images
    //             })

    //         utg_edge = {
    //             "from": from_state,
    //             "to": to_state,
    //             "id": from_state + "-->" + to_state,
    //             "title": list_to_html_table(event_short_descs),
    //             "label": ", ".join([str(x["event_id"]) for x in event_list]),
    //             "events": event_list
    //         }

    //         # # Highlight last transition
    //         # if state_transition == self.last_transition:
    //         #     utg_edge["color"] = "red"

    //         utg_edges.append(utg_edge)

    //     utg = {
    //         "nodes": utg_nodes,
    //         "edges": utg_edges,

    //         "num_nodes": len(utg_nodes),
    //         "num_edges": len(utg_edges),
    //         "num_effective_events": len(self.effective_event_strs),
    //         "num_reached_activities": len(self.reached_activities),
    //         "test_date": self.start_time.strftime("%Y-%m-%d %H:%M:%S"),
    //         "time_spent": (datetime.datetime.now() - self.start_time).total_seconds(),
    //         "num_transitions": self.num_transitions,

    //         "device_serial": self.device.serial,
    //         "device_model_number": self.device.get_model_number(),
    //         "device_sdk_version": self.device.get_sdk_version(),

    //         "app_sha256": self.app.hashes[2],
    //         "app_package": self.app.package_name,
    //         "app_main_activity": self.app.main_activity,
    //         "app_num_total_activities": len(self.app.activities),
    //     }

    //     utg_json = json.dumps(utg, indent=2)
    //     utg_file.write("var utg = \n")
    //     utg_file.write(utg_json)
    //     utg_file.close()
    // }
        
}

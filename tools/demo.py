"""Create an isolated synthetic demo; no inference and no access to a personal vault."""
import argparse,json,shutil,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import App,jsons,stamp,atomic_write

def create(target):
    target=Path(target).resolve()
    if target.exists():raise ValueError('Choose a new empty demo directory; existing data is never overwritten.')
    target.mkdir(parents=True)
    vault=target/'演示知识库';shutil.copytree(Path(__file__).resolve().parents[1]/'examples/demo-vault',vault)
    profile=target/'profile.json'
    profile.write_text(jsons({'adapter':'markdown','knowledge_root':str(vault),'workbench':{'name':'演示知识助手','demo':True,'runtime':str(target/'runtime'),'port':8877}}),'utf-8')
    app=App(profile)
    ident=app.save_idea({'text':'大家收藏了很多笔记，真正做事时却还是想不起来。我想聊聊：让一条笔记接上一个实际问题。','attribution':'personal'})['id']
    estimate=lambda tier:{'tier':tier,'basis':'演示暂估：未提供可比的历史作品，不是播放预测结果。','confidence':'不足','reference_ids':[]}
    original={'message':'让收藏的笔记在做事时用得上','audience':'习惯做笔记、整理资料的人','interest':'不想让花时间积累的知识闲置','limitation':'只谈笔记方法，容易错过遇到同样困境的职场人','estimate':estimate('5000')}
    dirs=[]
    for title,audience,expansion,opening,highlights,ending,goal,copy in [
        ('为什么学了那么多，遇到问题还是不会用？','经常学习，却在工作中难以迁移经验的人','笔记爱好者 → 想提升工作能力的人。从共同的“学过却不会用”进入，再回到一条笔记。','你有没有发现：课听懂了，笔记也记了，可下一次遇到问题，还是从头再来？',['用一次真实任务唤起笔记，而不是按文件夹复习。','把观点、案例和来源连起来，找回当时为什么这样想。','先用一条旧笔记解决小问题，再记录哪里有效。'],'知识能接上眼前的问题，积累才开始有用。','留言','你最近哪次遇到过“学过，但不会用”？'),
        ('别急着再学一个工具，先找回你已经会的东西','忙于寻找新工具、想减少重复劳动的创作者','整理资料的人 → 总觉得时间不够的创作者。先谈重复劳动，再谈知识复用。','你最缺的，可能不是下一个工具，而是上一次解决问题时留下的那段经验。',['从重复写过的一个问题切入，展示找回旧材料的过程。','同一个观点可以换场景，原话和事实不要乱改。','写完补一条使用反馈，下次知道从哪里继续。'],'让过去的自己，帮今天的自己少走一步弯路。','私信','想一起梳理自己的重复劳动，可以私信说说你的场景。')
    ]:
        dirs.append({'title':title,'audience':audience,'expansion':expansion,'promise':'从具体场景说明怎样调用旧知识','opening':opening,'hook_basis':'演示新拟开头，没有历史效果背书','structure':['共同困境','一条笔记的具体用途','三个可操作变化','一个小行动'],'word_count':420,'minutes':1.6,'confidence':'不足','goal':goal,'risk':'需补一个本人真实使用案例','scores':{'audience':4,'material':3,'promise':4,'distinctiveness':3,'transition':4},'score':72,'node_ids':[],'citations':[],'estimate':estimate('5万' if not dirs else '1万'),'highlights':highlights,'ending':ending,'conversion':{'goal':goal,'copy':copy,'path':'围绕读者提供的实际场景继续交流，不预设不存在的产品或赠品。'}})
    analysis={'original':original,'core':'先接住更多人遇到的困境，再把原来的知识讲清楚。','directions':dirs,'note':'预置演示，非模型实测','history_references':[],'model':'demo-fixture','version':'enhancer-v2'}
    draft=vault/'02_我的作品全集/工作台草稿/演示初稿.md'
    atomic_write(draft,'---\nstatus: draft_not_final\nauthorship: demo_fixture\n---\n# 为什么学了那么多，遇到问题还是不会用？\n\n> 预置演示初稿，用于展示阅读流程，非模型实测。\n\n你有没有发现：课听懂了，笔记也记了，可下一次遇到问题，还是从头再来？\n\n有时候，问题出在我们只记住了这条笔记放在哪里，没有记住它能帮忙解决什么。\n\n下次做一个具体任务，先别急着找新资料。试着找回一条过去的记录：当时遇到了什么，为什么作出那个判断，最后有没有奏效。\n\n再把它与一个案例连起来。观点让你看方向，案例告诉你它在什么情况下有用，原文让你核对自己有没有记错。\n\n最后，只挑一个小地方试一次。写文章时借用一个解释，开会时用上一个问题，做方案时检验一个判断。用完再留下反馈。\n\n知识能接上眼前的问题，积累才开始有用。\n\n你最近哪次遇到过“学过，但不会用”？\n')
    with app.db() as db:
        db.execute("update ideas set analysis=?,status='drafted',selected=0,draft_path=? where id=?",(jsons(analysis),str(draft),ident))
        evidence=app.k.search('笔记 知识 问题')['passages'][:2]
        db.execute('insert into messages(role,text,created,citations) values(?,?,?,?)',('user','怎样让整理好的知识，真正进入我的日常工作？',stamp(),'[]'))
        answer='**下面是预置演示回答，用于展示对话与来源。**\n\n可以从你今天要解决的一件事开始。先找一条相关笔记，看看它当时针对什么问题，再判断能不能用在现在。\n\n比如准备一篇文章，先找回一个观点，再读对应的案例和原始记录。这样拿到的就不只是一个结论，还有当时的理由。\n\n用过之后，补一句反馈：这次哪里有效、哪里需要修改。下一次遇到相似问题，就能从这次继续。'
        db.execute('insert into messages(role,text,created,citations) values(?,?,?,?)',('assistant',answer,stamp(),jsons(evidence)))
    app.save_idea({'text':'一次复盘不只看结果，还要回到当时为什么这样选择。','attribution':'personal'})
    return profile

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path,default=Path('.local/demo'));a=p.parse_args()
    print(create(a.directory))

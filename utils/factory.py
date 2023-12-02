def get_model(model_name, args):
    name = model_name.lower()
    if name=="simplecil":
        from models.simplecil import Learner
        return Learner(args)
    elif name=="slca":
        from models.SLCA import SLCA
        return SLCA(args)
    elif name=="adapt_tta":
        from models.adapt_tta import Learner
        return Learner(args)
    elif name=="finetune":
        from models.finetune import Learner
        return Learner(args)
    elif name=="adapter":
        from models.finetune import Learner
        return Learner(args)
    else:
        assert 0

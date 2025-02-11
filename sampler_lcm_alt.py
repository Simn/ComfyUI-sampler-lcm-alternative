import comfy.samplers
from comfy.k_diffusion.sampling import default_noise_sampler
from tqdm.auto import trange, tqdm
from itertools import product
import torch

@torch.no_grad()
def sample_lcm_alt(model, x, sigmas, extra_args=None, callback=None, disable=None, noise_sampler=None, euler_steps=0, ancestral=0.0, noise_mult = 1.0):
    extra_args = {} if extra_args is None else extra_args
    noise_sampler = default_noise_sampler(x) if noise_sampler is None else noise_sampler
    s_in = x.new_ones([x.shape[0]])
    steps = len(sigmas)-1
    euler_limit = euler_steps%steps
    loop_control = [True] * euler_limit + [False] * (steps - euler_limit)
    return sample_lcm_backbone(model, x, sigmas, extra_args, callback, disable, noise_sampler, loop_control, ancestral, noise_mult)

@torch.no_grad()
def sample_lcm_cycle(model, x, sigmas, extra_args=None, callback=None, disable=None, noise_sampler=None, euler_steps = 1, lcm_steps = 1, tweak_sigmas = False, ancestral=0.0):
    extra_args = {} if extra_args is None else extra_args
    noise_sampler = default_noise_sampler(x) if noise_sampler is None else noise_sampler
    s_in = x.new_ones([x.shape[0]])
    steps = len(sigmas) - 2
    cycle_length = euler_steps + lcm_steps
    repeats = steps // (cycle_length)
    leftover = steps % (cycle_length)
    cycle = [True] * euler_steps + [False] * lcm_steps
    loop_control = cycle * repeats + cycle[-leftover:] #+ [False]
    if tweak_sigmas:
        index_map = torch.tensor([i + j * repeats for i,j in product(range(repeats),range(cycle_length))] +
                                 list(range(cycle_length*repeats,len(sigmas)))).to(sigmas.device)
        sigmas = torch.index_select(sigmas, 0, index_map)
    return sample_lcm_backbone(model, x, sigmas, extra_args, callback, disable, noise_sampler, loop_control, ancestral)

@torch.no_grad()
def sample_lcm_backbone(model, x, sigmas, extra_args, callback, disable, noise_sampler, loop_control, ancestral, noise_mult = 1.0):
    s_in = x.new_ones([x.shape[0]])
    for i in trange(len(sigmas) - 1, disable=disable):
        denoised = model(x, sigmas[i] * s_in, **extra_args)
        if callback is not None:
            callback({'x': x, 'i': i, 'sigma': sigmas[i], 'sigma_hat': sigmas[i], 'denoised': denoised})

        if sigmas[i + 1] > 0:
            if loop_control[i]:
                if ancestral < 1.0:
                    removed_noise = (x - denoised) / sigmas[i]
                if ancestral > 0.0:
                    noise = noise_sampler(sigmas[i], sigmas[i + 1])
                    if ancestral < 1.0:
                        noise = (ancestral**0.5) * noise + ((1.0 - ancestral)**0.5) * removed_noise
                elif ancestral == 0.0:
                    noise = removed_noise*noise_mult
            else:
                noise = noise_sampler(sigmas[i], sigmas[i + 1])
        else:
            noise = None
        x = denoised
        if noise is not None:
            x += sigmas[i + 1] * noise
    return x

class LCMScheduler:
    @classmethod
    def INPUT_TYPES(s):
        return {"required":
                    {"model": ("MODEL",),
                     "steps": ("INT", {"default": 8, "min": 1, "max": 10000}),
                      }
               }
    RETURN_TYPES = ("SIGMAS",)
    CATEGORY = "sampling/custom_sampling/schedulers"

    FUNCTION = "get_sigmas"

    def get_sigmas(self, model, steps):
        sigmas = comfy.samplers.calculate_sigmas_scheduler(model.model, "sgm_uniform", steps).cpu()
        return (sigmas, )

class SamplerLCMAlternative:
    @classmethod
    def INPUT_TYPES(s):
        return {"required":
                    {"euler_steps": ("INT", {"default": 0, "min": -10000, "max": 10000}),
                     "ancestral": ("FLOAT", {"default": 0, "min": 0, "max": 1.0, "step": 0.01, "round": True}),
                     "noise_mult": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.001, "round": True}),
                    }
               }
    RETURN_TYPES = ("SAMPLER",)
    CATEGORY = "sampling/custom_sampling/samplers"

    FUNCTION = "get_sampler"

    def get_sampler(self, euler_steps, ancestral, noise_mult):
        sampler = comfy.samplers.KSAMPLER(sample_lcm_alt, extra_options={"euler_steps": euler_steps, "noise_mult": noise_mult, "ancestral": ancestral})
        return (sampler, )

class SamplerLCMCycle:
    @classmethod
    def INPUT_TYPES(s):
        return {"required":
                    {"euler_steps": ("INT", {"default": 1, "min": 1, "max": 50}),
                     "lcm_steps": ("INT", {"default": 2, "min": 1, "max": 50}),
                     "tweak_sigmas": ("BOOLEAN", {"default": False}),
                     "ancestral": ("FLOAT", {"default": 0, "min": 0, "max": 1.0, "step": 0.01, "round": False}),
                    }
               }
    RETURN_TYPES = ("SAMPLER",)
    CATEGORY = "sampling/custom_sampling/samplers"

    FUNCTION = "get_sampler"

    def get_sampler(self, euler_steps, lcm_steps, tweak_sigmas, ancestral):
        sampler = comfy.samplers.KSAMPLER(sample_lcm_cycle, extra_options={"euler_steps": euler_steps, "lcm_steps": lcm_steps, "tweak_sigmas": tweak_sigmas, "ancestral": ancestral})
        return (sampler, )


NODE_CLASS_MAPPINGS = {
    "LCMScheduler": LCMScheduler,
    "SamplerLCMAlternative": SamplerLCMAlternative,
    "SamplerLCMCycle": SamplerLCMCycle,
}

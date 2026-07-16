
from datetime import date

from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand
from django.db import transaction


DEMO_PASSWORD = "Demo@1234"
TODAY = date.today().isoformat()


class Command(BaseCommand):
    help = "Seed a full demo FMCG hierarchy for development testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            
            action="store_true",
            help="Delete all entities, entity types, and channels before seeding.",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            self._reset()

        self.stdout.write("\n--- Step 1: Roles ---")
        self._ensure_roles()

        self.stdout.write("\n--- Step 2: Channels ---")
        channels = self._seed_channels()

        self.stdout.write("\n--- Step 3: Node Types ---")
        et = self._seed_entity_types()

        self.stdout.write("\n--- Step 4: Geography ---")
        geo = self._seed_geography()

        self.stdout.write("\n--- Step 5: Hierarchy ---")
        self._seed_hierarchy(et, channels, geo)
        self._backdate_assignments()

        self.stdout.write("\n--- Step 6: Admin User ---")
        self._ensure_admin()

        self._print_credentials()



    @transaction.atomic
    def _reset(self):
        from apps.accounts.models import User
        from apps.assignments.models import Assignment
        from apps.hierarchy.models import (
            Channel, Node, NodeRelationship, NodeType,
            GeographyNode, GeographyType,
        )

        from apps.targets.models import TargetPlan

        # Plans PROTECT their root geography — clear them (runs/tasks cascade) before the tree.
        TargetPlan.objects.all().delete()
        # The Assignment bridge (assignee → Node, on_delete=PROTECT) must go before the tree.
        Assignment.objects.all().delete()
        NodeRelationship.objects.all().delete()
        Node.objects.all().delete()
        NodeType.objects.all().delete()
        GeographyNode.objects.all().delete()
        GeographyType.objects.all().delete()
        Channel.objects.all().delete()
        User.objects.filter(is_superuser=False, is_staff=False).delete()
        self.stdout.write(self.style.WARNING("  Reset complete."))



    def _ensure_roles(self):
        from django.core.management import call_command
        call_command("seed_roles", verbosity=0)
        self.stdout.write("  Roles ready.")

    def _backdate_assignments(self):
        from datetime import timedelta

        from apps.assignments.models import Assignment

        # Demo periods live in the recent past (previous + current month); ownership must
        # already be effective there or every "as of" resolution comes back empty.
        backdated = Assignment.objects.filter(effective_from__gte=TODAY).update(
            effective_from=date.today() - timedelta(days=365))
        if backdated:
            self.stdout.write(f"  Backdated {backdated} owner assignment(s) one year for demo history.")



    def _seed_channels(self):
        from apps.hierarchy.models import Channel

        channel_data = [
            {"code": "GT",    "name": "General Trade",  "description": "Kirana stores, local retailers"},
            {"code": "MT",    "name": "Modern Trade",   "description": "Supermarkets, hypermarkets, chains"},
            {"code": "RURAL", "name": "Rural",          "description": "Villages and semi-urban markets"},
        ]
        channels = {}
        for d in channel_data:
            ch, created = Channel.objects.get_or_create(
                code=d["code"],
                defaults={"name": d["name"], "description": d["description"]},
            )
            channels[d["code"]] = ch
            mark = "[+]" if created else "[~]"
            self.stdout.write(f"  {mark} Channel {d['code']}: {d['name']}")
        return channels



    def _seed_geography(self):
        """A small but realistic sales geography: region → state → district → town.

        Returns a dict of nodes keyed by code so the hierarchy step can pin entities.
        """
        from apps.hierarchy.models import GeographyNode, GeographyType
        from apps.hierarchy.config_services import GeographyNodeService, GeographyTypeService

        geo_type = GeographyType.objects.filter(code="sales_geo").first()
        if geo_type is None:
            geo_type = GeographyTypeService.create({
                "name": "Sales Geography",
                "code": "sales_geo",
                "levels": ["nation", "region", "state", "district", "town"],
            })
        self.stdout.write(f"  Geography type: {geo_type.name} {geo_type.levels}")

        nodes = {}

        def _node(code, name, level, parent_code=None):
            existing = GeographyNode.objects.filter(code=code, is_active=True).first()
            if existing:
                nodes[code] = existing
                self.stdout.write(f"  [~] {level}: {name}")
                return existing
            node = GeographyNodeService.create({
                "geography_type": geo_type,
                "name": name,
                "code": code,
                "level": level,
                "parent": nodes[parent_code] if parent_code else None,
            })
            nodes[code] = node
            self.stdout.write(self.style.SUCCESS(f"  [+] {level}: {name}"))
            return node

        # nation → region → state → district → town. The single nation root lets the top
        # manager (NSM) own one territory whose subtree rolls up the whole network.
        _node("GEO_IN", "India", "nation")
        _node("GEO_NORTH", "North", "region", "GEO_IN")
        _node("GEO_DL", "Delhi", "state", "GEO_NORTH")
        _node("GEO_UP", "Uttar Pradesh", "state", "GEO_NORTH")
        _node("GEO_DL_NEW", "New Delhi", "district", "GEO_DL")
        _node("GEO_DL_WEST", "West Delhi", "district", "GEO_DL")
        _node("GEO_UP_NOIDA", "Noida", "district", "GEO_UP")

        _node("GEO_SOUTH", "South", "region", "GEO_IN")
        _node("GEO_KA", "Karnataka", "state", "GEO_SOUTH")
        _node("GEO_KA_BLR", "Bangalore", "district", "GEO_KA")

        return nodes



    def _seed_entity_types(self):
        from apps.accounts.models import Role
        from apps.hierarchy.models import NodeType

        def _get_role(code):
            return Role.objects.filter(code=code, is_active=True).first()

        def _make_et(data):
            et = NodeType.objects.filter(code=data["code"], is_current=True).first()
            if et:
                self.stdout.write(f"  [~] NodeType {data['code']}: {data['name']}")
                return et
            et = NodeType.objects.create(
                name=data["name"],
                code=data["code"],
                description=data.get("description", ""),
                level_order=data["level_order"],
                allowed_parent_types=data.get("allowed_parent_types", []),
                allowed_child_types=data.get("allowed_child_types", []),
                attribute_schema=data.get("attribute_schema", []),
                is_loginable=data.get("is_loginable", False),
                incentive_eligible=data.get("incentive_eligible", False),
                is_leaf=data.get("is_leaf", False),
                default_role=data.get("default_role"),
                display_config=data.get("display_config", {}),
                effective_from=date.today(),
                version=1,
                is_current=True,
            )
            self.stdout.write(self.style.SUCCESS(f"  [+] NodeType {data['code']}: {data['name']}"))
            return et

        ff_schema = [  # Field-force attribute schema
            {"key": "employee_id", "label": "Employee ID", "type": "string",
             "required": True, "unique": True},
            {"key": "joining_date", "label": "Date of Joining", "type": "date",
             "required": False, "unique": False},
        ]
        dist_schema = [
            {"key": "gstin",        "label": "GSTIN",   "type": "string",  "required": False, "unique": True},
            {"key": "credit_limit", "label": "Credit Limit (₹)", "type": "decimal", "required": False, "unique": False},
        ]
        retailer_schema = [
            {"key": "store_class",        "label": "Store Class",             "type": "choice",  "required": True,
             "unique": False, "options": ["A", "B", "C", "D"]},
            {"key": "monthly_potential",  "label": "Monthly Potential (₹)",  "type": "decimal", "required": False, "unique": False},
        ]

        et = {}

        et["nsm"] = _make_et({
            "name": "National Sales Manager", "code": "nsm", "level_order": 1,
            "allowed_parent_types": [], "allowed_child_types": ["rsm"],
            "attribute_schema": ff_schema,
            "is_loginable": True, "incentive_eligible": True,
            "default_role": _get_role("national_head"),
            "display_config": {"color": "#1e40af", "portal_type": "admin",
                               "login_method": "password_and_otp", "show_in_tree": True,
                               "icon": "crown", "card_fields": ["employee_id"]},
        })

        et["rsm"] = _make_et({
            "name": "Regional Sales Manager", "code": "rsm", "level_order": 2,
            "allowed_parent_types": ["nsm"], "allowed_child_types": ["asm"],
            "attribute_schema": ff_schema,
            "is_loginable": True, "incentive_eligible": True,
            "default_role": _get_role("regional_manager"),
            "display_config": {"color": "#7c3aed", "portal_type": "admin",
                               "login_method": "password_and_otp", "show_in_tree": True,
                               "icon": "user-tie", "card_fields": ["employee_id"]},
        })

        et["asm"] = _make_et({
            "name": "Area Sales Manager", "code": "asm", "level_order": 3,
            "allowed_parent_types": ["rsm"], "allowed_child_types": ["ase"],
            "attribute_schema": ff_schema,
            "is_loginable": True, "incentive_eligible": True,
            "default_role": _get_role("area_manager"),
            "display_config": {"color": "#059669", "portal_type": "admin",
                               "login_method": "password_and_otp", "show_in_tree": True,
                               "icon": "briefcase", "card_fields": ["employee_id"]},
        })

        et["ase"] = _make_et({
            "name": "Area Sales Executive", "code": "ase", "level_order": 4,
            "allowed_parent_types": ["asm"], "allowed_child_types": ["distributor"],
            "attribute_schema": ff_schema,
            "is_loginable": True, "incentive_eligible": True,
            "default_role": _get_role("sales_exec"),
            "display_config": {"color": "#d97706", "portal_type": "admin",
                               "login_method": "password_and_otp", "show_in_tree": True,
                               "icon": "user", "card_fields": ["employee_id"]},
        })

        et["distributor"] = _make_et({
            "name": "Distributor", "code": "distributor", "level_order": 5,
            "allowed_parent_types": ["ase"], "allowed_child_types": ["retailer"],
            "attribute_schema": dist_schema,
            "is_loginable": True,
            "default_role": _get_role("distributor"),
            "display_config": {"color": "#dc2626", "portal_type": "partner",
                               "login_method": "otp_only", "show_in_tree": True,
                               "icon": "truck", "card_fields": ["gstin", "credit_limit"]},
        })

        et["retailer"] = _make_et({
            "name": "Retailer", "code": "retailer", "level_order": 6,
            "allowed_parent_types": ["distributor"], "allowed_child_types": [],
            "attribute_schema": retailer_schema,
            "is_loginable": True, "is_leaf": True,
            "default_role": _get_role("retailer"),
            "display_config": {"color": "#db2777", "portal_type": "partner",
                               "login_method": "otp_only", "show_in_tree": True,
                               "icon": "store", "card_fields": ["store_class"]},
        })

        return et



    def _seed_hierarchy(self, et, channels, geo):
        from apps.hierarchy.services import NodeService

        gt = channels["GT"]

        def _make(code, name, entity_type, parent=None,
                  attrs=None, email=None, mobile=None, channel=None, geo_code=None):
            from apps.hierarchy.models import Node
            existing = Node.objects.filter(code=code, is_current=True).first()
            if existing:
                self.stdout.write(f"  [~] {code}: {name}")
                return existing

            data = {
                "entity_type_id": entity_type.id,
                "name": name,
                "code": code,
                "attributes": attrs or {},
                "effective_from": TODAY,
                "channel_id": (channel or gt).pk,
            }
            if parent:
                data["parent_id"] = parent.id
            if email:
                data["email"] = email
            if mobile:
                data["mobile"] = mobile

            # Two-tree bridge: territory coverage is an owner Assignment, created with
            # the entity. A territory has at most one owner — many entities (ASE +
            # distributors + retailers) sit in the same demo node, so only the first
            # claimant owns it; the rest have no territory link at all.
            if geo_code and geo_code in geo:
                from apps.assignments.services import AssignmentService
                scope = geo[geo_code]
                if AssignmentService.owner_of(scope.pk, on=date.today()) is None:
                    data["owned_scope_ids"] = [scope.pk]

            entity = NodeService.create_entity(data, user=None)
            self.stdout.write(self.style.SUCCESS(f"  [+] {code}: {name}"))
            return entity

        def _set_password(entity):

            try:
                u = entity.user  # OneToOne reverse accessor
                u.set_password(DEMO_PASSWORD)
                u.save(update_fields=["password"])
            except ObjectDoesNotExist:
                pass


        nsm = _make("NSM_001", "Rajesh Sharma",
                    et["nsm"], email="nsm@thriive.com",
                    attrs={"employee_id": "EMP001"}, geo_code="GEO_IN")
        _set_password(nsm)

        rsm_north = _make("RSM_NORTH", "Amit Kumar",
                          et["rsm"], parent=nsm, email="rsm.north@thriive.com",
                          attrs={"employee_id": "EMP002"}, geo_code="GEO_NORTH")
        _set_password(rsm_north)

        rsm_south = _make("RSM_SOUTH", "Kavitha Reddy",
                          et["rsm"], parent=nsm, email="rsm.south@thriive.com",
                          attrs={"employee_id": "EMP003"}, geo_code="GEO_SOUTH")
        _set_password(rsm_south)

        asm_delhi = _make("ASM_DL", "Priya Singh",
                          et["asm"], parent=rsm_north, email="asm.delhi@thriive.com",
                          attrs={"employee_id": "EMP004"}, geo_code="GEO_DL")
        _set_password(asm_delhi)

        asm_noida = _make("ASM_NDA", "Vijay Gupta",
                          et["asm"], parent=rsm_north, email="asm.noida@thriive.com",
                          attrs={"employee_id": "EMP005"}, geo_code="GEO_UP")
        _set_password(asm_noida)

        asm_blr = _make("ASM_BLR", "Suresh Nair",
                        et["asm"], parent=rsm_south, email="asm.bangalore@thriive.com",
                        attrs={"employee_id": "EMP006"}, geo_code="GEO_KA")
        _set_password(asm_blr)

        ase_dl_e = _make("ASE_DL_E", "Rahul Kumar",
                         et["ase"], parent=asm_delhi, email="ase.delhi.east@thriive.com",
                         attrs={"employee_id": "EMP007"}, geo_code="GEO_DL_NEW")
        _set_password(ase_dl_e)

        ase_dl_w = _make("ASE_DL_W", "Sunita Patel",
                         et["ase"], parent=asm_delhi, email="ase.delhi.west@thriive.com",
                         attrs={"employee_id": "EMP008"}, geo_code="GEO_DL_WEST")
        _set_password(ase_dl_w)

        ase_nda = _make("ASE_NDA", "Deepa Mishra",
                        et["ase"], parent=asm_noida, email="ase.noida@thriive.com",
                        attrs={"employee_id": "EMP009"}, geo_code="GEO_UP_NOIDA")
        _set_password(ase_nda)

        ase_blr = _make("ASE_BLR", "Anita Krishnan",
                        et["ase"], parent=asm_blr, email="ase.bangalore@thriive.com",
                        attrs={"employee_id": "EMP010"}, geo_code="GEO_KA_BLR")
        _set_password(ase_blr)



        dist1 = _make("DIST_DL_E_01", "Sharma Distributors",
                      et["distributor"], parent=ase_dl_e, mobile="9876543201",
                      attrs={"gstin": "07AABCS1429B1Z6", "credit_limit": "500000"},
                      geo_code="GEO_DL_NEW")

        dist2 = _make("DIST_DL_E_02", "Verma Traders",
                      et["distributor"], parent=ase_dl_e, mobile="9876543202",
                      attrs={"gstin": "07AAACV2345G1Z9", "credit_limit": "300000"},
                      geo_code="GEO_DL_NEW")

        dist3 = _make("DIST_DL_W_01", "Jain Distributors",
                      et["distributor"], parent=ase_dl_w, mobile="9876543203",
                      attrs={"gstin": "07AAAJD5678H1Z3", "credit_limit": "400000"},
                      geo_code="GEO_DL_WEST")

        dist4 = _make("DIST_NDA_01", "Pandey Traders",
                      et["distributor"], parent=ase_nda, mobile="9876543204",
                      attrs={"credit_limit": "250000"}, geo_code="GEO_UP_NOIDA")

        dist5 = _make("DIST_BLR_01", "Nair Distributors",
                      et["distributor"], parent=ase_blr, mobile="9876543205",
                      attrs={"credit_limit": "600000"}, geo_code="GEO_KA_BLR")



        _make("RET_001", "Krishna Store",
              et["retailer"], parent=dist1, mobile="9876543301",
              attrs={"store_class": "A", "monthly_potential": "80000"})

        _make("RET_002", "Gupta Medical",
              et["retailer"], parent=dist1, mobile="9876543302",
              attrs={"store_class": "B", "monthly_potential": "50000"})

        _make("RET_003", "Singh Pharmacy",
              et["retailer"], parent=dist2, mobile="9876543303",
              attrs={"store_class": "A", "monthly_potential": "70000"})

        _make("RET_004", "Jain Store",
              et["retailer"], parent=dist3, mobile="9876543304",
              attrs={"store_class": "C", "monthly_potential": "35000"})

        _make("RET_005", "Patel Medical Hall",
              et["retailer"], parent=dist3, mobile="9876543305",
              attrs={"store_class": "B", "monthly_potential": "55000"})

        _make("RET_006", "Soni Medicals",
              et["retailer"], parent=dist4, mobile="9876543306",
              attrs={"store_class": "B", "monthly_potential": "45000"})

        _make("RET_007", "Rao Medical",
              et["retailer"], parent=dist5, mobile="9876543307",
              attrs={"store_class": "A", "monthly_potential": "90000"})

        _make("RET_008", "Pillai Store",
              et["retailer"], parent=dist5, mobile="9876543308",
              attrs={"store_class": "C", "monthly_potential": "30000"})



    def _ensure_admin(self):
        from apps.accounts.models import Role, User, UserRole

        user, created = User.objects.get_or_create(
            email="admin@thriive.com",
            defaults={
                "first_name": "Thriive",
                "last_name": "Admin",
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )
        if created or not user.has_usable_password():
            user.set_password("Admin@1234")
            user.save(update_fields=["password", "is_staff", "is_superuser"])

        # Assign admin role so the frontend RBAC hook sees 'full' on all resources
        admin_role = Role.objects.filter(code="admin", is_active=True).first()
        if admin_role:
            UserRole.objects.get_or_create(
                user=user,
                role=admin_role,
                defaults={"effective_from": date.today()},
            )

        mark = "[+]" if created else "[~]"
        self.stdout.write(f"  {mark} admin@thriive.com  (Admin@1234)")



    def _print_credentials(self):
        from apps.hierarchy.models import Node

        width = 72
        div = "=" * width

        self.stdout.write(f"\n{div}")
        self.stdout.write(self.style.SUCCESS("  DEMO CREDENTIALS -- Thriive IMS"))
        self.stdout.write(div)

        self.stdout.write(f"\n  {'ROLE':<22} {'EMAIL / MOBILE':<34} {'PASSWORD / AUTH'}")
        self.stdout.write(f"  {'-' * 70}")

        # Admin
        self.stdout.write(f"\n  {'[Superuser]'}")
        self.stdout.write(f"  {'Admin':<22} {'admin@thriive.com':<34} Admin@1234")

        # Field force
        ff_accounts = [
            ("NSM",  "nsm@thriive.com"),
            ("RSM",  "rsm.north@thriive.com"),
            ("RSM",  "rsm.south@thriive.com"),
            ("ASM",  "asm.delhi@thriive.com"),
            ("ASM",  "asm.noida@thriive.com"),
            ("ASM",  "asm.bangalore@thriive.com"),
            ("ASE",  "ase.delhi.east@thriive.com"),
            ("ASE",  "ase.delhi.west@thriive.com"),
            ("ASE",  "ase.noida@thriive.com"),
            ("ASE",  "ase.bangalore@thriive.com"),
        ]
        self.stdout.write("\n  [Field Force - password login]")
        for role, email in ff_accounts:
            self.stdout.write(f"  {role:<22} {email:<34} {DEMO_PASSWORD}")

        # Channel partners
        self.stdout.write("\n  [Channel Partners - OTP login]")
        self.stdout.write(f"  {'Request OTP:':<22} POST /api/v1/auth/login/otp/request/  {{\"identifier\": \"<mobile>\"}}")
        self.stdout.write(f"  {'OTP note:':<22} Appears in Django console (dev mode)")
        partner_data = [
            ("Distributor", "9876543201", "Sharma Distributors"),
            ("Distributor", "9876543202", "Verma Traders"),
            ("Distributor", "9876543203", "Jain Distributors"),
            ("Distributor", "9876543204", "Pandey Traders"),
            ("Distributor", "9876543205", "Nair Distributors"),
            ("Retailer",    "9876543301", "Krishna Store"),
            ("Retailer",    "9876543302", "Gupta Medical"),
            ("Retailer",    "9876543303", "Singh Pharmacy"),
            ("Retailer",    "9876543304", "Jain Store"),
            ("Retailer",    "9876543305", "Patel Medical Hall"),
            ("Retailer",    "9876543306", "Soni Medicals"),
            ("Retailer",    "9876543307", "Rao Medical"),
            ("Retailer",    "9876543308", "Pillai Store"),
        ]
        for role, mobile, name in partner_data:
            self.stdout.write(f"  {role:<22} {mobile:<34} {name}")

        self.stdout.write(f"\n  {'[Swagger UI]'}")
        self.stdout.write(f"  http://localhost:8000/api/docs/")

        self.stdout.write(f"\n  {'[Frontend]'}")
        self.stdout.write(f"  http://localhost:5173/")

        # Quick tree view
        self.stdout.write(f"\n  {'[Hierarchy Tree]'}")
        try:
            nsm = Node.objects.filter(code="NSM_001", is_current=True).first()
            if nsm:
                self._print_tree(nsm, "  ", "")
        except Exception:  # noqa: BLE001
            pass

        self.stdout.write(f"\n{'=' * width}\n")

    def _print_tree(self, entity, prefix, child_prefix, depth=0):
        if depth > 6:
            return
        self.stdout.write(f"{prefix}{entity.code}  {entity.name}")
        children = list(
            type(entity).objects.filter(parent=entity, is_current=True, is_active=True)
            .order_by("code")
        )
        for i, child in enumerate(children):
            is_last = i == len(children) - 1
            connector = "+-- " if is_last else "+-- "
            self.stdout.write(f"{child_prefix}{connector}", ending="")
            self._print_tree(
                child,
                "",
                child_prefix + ("    " if is_last else "|   "),
                depth + 1,
            )
